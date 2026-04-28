"""
Bolna -> Slack integration (production setup).

- Lifespan-managed Redis & httpx clients.
- IP whitelist + shared-secret auth on /webhook.
- Rate limiting (slowapi).
- Background processing so webhook returns 200 fast.
- Atomic Redis-based dedupe (SET NX EX).
- Slack delivery with exponential-backoff retries.
- Structured JSON logging with request IDs.
- /healthz (liveness) and /readyz (readiness).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import Settings, get_settings
from app.dedupe import DedupeStore, InMemoryDedupeStore, RedisDedupeStore
from app.logging_config import (
    configure_logging,
    get_logger,
    new_request_id,
    request_id_var,
)
from app.models import BolnaExecution
from app.security import verify_ip, verify_token
from app.slack_client import SlackClient, SlackDeliveryError

logger = get_logger("api")

# A call has "ended" when status is one of these.
# https://www.bolna.ai/docs/api-reference/executions/get_execution
TERMINAL_STATUSES = frozenset(
    {
        "completed",
        "call-disconnected",
        "no-answer",
        "busy",
        "failed",
        "canceled",
    }
)


# --------------------------------------------------------------------------- #
# Lifespan: build & teardown shared clients
# --------------------------------------------------------------------------- #
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)

    # Redis (with graceful fallback for local dev / tests)
    dedupe: DedupeStore
    redis_store = RedisDedupeStore(settings.redis_url)
    if await redis_store.ping():
        dedupe = redis_store
        logger.info("redis_connected", url=settings.redis_url)
    else:
        await redis_store.aclose()
        dedupe = InMemoryDedupeStore()
        logger.warning("redis_unavailable_using_memory")

    # Shared HTTP client for Slack (connection pooling, keep-alive)
    http = httpx.AsyncClient(
        timeout=settings.slack_request_timeout,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )
    slack = SlackClient(settings, client=http)

    app.state.settings = settings
    app.state.dedupe = dedupe
    app.state.slack = slack
    app.state.http = http

    logger.info("startup_complete", env=settings.environment)
    try:
        yield
    finally:
        logger.info("shutting_down")
        await slack.aclose()
        await http.aclose()
        await dedupe.aclose()


# --------------------------------------------------------------------------- #
# App + middleware
# --------------------------------------------------------------------------- #
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="Bolna → Slack Integration",
    version="1.0.0",
    lifespan=lifespan,
)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"error": "rate_limit_exceeded", "detail": str(exc.detail)},
    )


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    rid = new_request_id()
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    return response


# --------------------------------------------------------------------------- #
# Dependencies
# --------------------------------------------------------------------------- #
def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_dedupe(request: Request) -> DedupeStore:
    return request.app.state.dedupe


def get_slack(request: Request) -> SlackClient:
    return request.app.state.slack


# --------------------------------------------------------------------------- #
# Background processor
# --------------------------------------------------------------------------- #
async def process_execution(
    execution: BolnaExecution,
    dedupe: DedupeStore,
    slack: SlackClient,
    settings: Settings,
    request_id: str,
) -> None:
    # Re-establish request_id in this background task
    request_id_var.set(request_id)

    if execution.status not in TERMINAL_STATUSES:
        logger.info(
            "skipped_non_terminal",
            execution_id=execution.id,
            status=execution.status,
        )
        return

    acquired = await dedupe.acquire(execution.id, settings.dedupe_ttl_seconds)
    if not acquired:
        logger.info("skipped_duplicate", execution_id=execution.id)
        return

    try:
        await slack.send(execution)
        logger.info(
            "alert_dispatched",
            execution_id=execution.id,
            agent_id=execution.agent_id,
            duration=execution.effective_duration,
        )
    except SlackDeliveryError as e:
        logger.error(
            "alert_failed", execution_id=execution.id, error=str(e), exc_info=True
        )
        # Note: at this point we've already returned 200 to Bolna.
        # In a higher-stakes setup, push to a dead-letter queue here.


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.get("/healthz")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
async def readiness(request: Request) -> JSONResponse:
    dedupe: DedupeStore = request.app.state.dedupe
    ready = True
    checks: dict[str, str] = {}

    if isinstance(dedupe, RedisDedupeStore):
        ok = await dedupe.ping()
        checks["redis"] = "ok" if ok else "down"
        if not ok:
            ready = False
    else:
        checks["redis"] = "memory_fallback"

    code = status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=code, content={"ready": ready, "checks": checks})


@app.post("/webhook")
@limiter.limit("120/minute")
async def bolna_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_app_settings),
    dedupe: DedupeStore = Depends(get_dedupe),
    slack: SlackClient = Depends(get_slack),
) -> dict[str, bool]:
    # 1. Auth
    verify_ip(request, settings)
    verify_token(request, settings)

    # 2. Parse
    try:
        raw = await request.json()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON body"
        ) from e

    try:
        execution = BolnaExecution.model_validate(raw)
    except ValidationError as e:
        logger.warning("payload_validation_failed", errors=e.errors())
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=e.errors(),
        ) from e

    logger.info(
        "webhook_received",
        execution_id=execution.id,
        agent_id=execution.agent_id,
        status_=execution.status,
    )

    # 3. Hand off to background — return 200 immediately so Bolna doesn't retry on slow Slack
    background_tasks.add_task(
        process_execution,
        execution,
        dedupe,
        slack,
        settings,
        request_id_var.get(),
    )
    return {"received": True}
