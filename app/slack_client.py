"""Slack Incoming Webhook client with retries."""

import asyncio
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import Settings
from app.logging_config import get_logger
from app.models import BolnaExecution

logger = get_logger("slack")


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "N/A"
    seconds = int(seconds)
    minutes, sec = divmod(seconds, 60)
    return f"{minutes}m {sec}s" if minutes else f"{sec}s"


def _truncate(text: str, limit: int = 2800) -> str:
    """Slack section text fields cap at 3000 chars; leave headroom."""
    return text if len(text) <= limit else text[:limit] + "\n…(truncated)"


def build_payload(execution: BolnaExecution) -> dict[str, Any]:
    duration = format_duration(execution.effective_duration)
    transcript = execution.transcript or "_No transcript available_"

    return {
        "text": f"📞 Bolna call ended — {execution.id}",
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "📞 Bolna Call Ended"},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Execution ID:*\n`{execution.id}`"},
                    {"type": "mrkdwn", "text": f"*Agent ID:*\n`{execution.agent_id}`"},
                    {"type": "mrkdwn", "text": f"*Duration:*\n{duration}"},
                    {"type": "mrkdwn", "text": f"*Status:*\n`{execution.status}`"},
                ],
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Transcript:*\n```{_truncate(str(transcript))}```",
                },
            },
        ],
    }


class SlackClient:
    """Posts to a Slack Incoming Webhook with retries on transient errors."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self._settings = settings
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=settings.slack_request_timeout
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def send(self, execution: BolnaExecution) -> None:
        url = self._settings.slack_webhook_url.get_secret_value()
        body = build_payload(execution)

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self._settings.slack_max_retries),
                wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
                retry=retry_if_exception_type(
                    (httpx.TransportError, httpx.HTTPStatusError, asyncio.TimeoutError)
                ),
                reraise=True,
            ):
                with attempt:
                    response = await self._client.post(url, json=body)
                    # Slack returns 200 with body 'ok' on success.
                    # 4xx (except 429) is non-retriable, 5xx and 429 are retriable.
                    if response.status_code == 429 or response.status_code >= 500:
                        response.raise_for_status()
                    elif response.status_code >= 400:
                        # Non-retriable client error — log body, raise immediately
                        logger.error(
                            "slack_non_retriable_error",
                            status=response.status_code,
                            body=response.text[:500],
                            execution_id=execution.id,
                        )
                        raise SlackDeliveryError(
                            f"Slack {response.status_code}: {response.text[:200]}"
                        )

                    logger.info(
                        "slack_alert_sent",
                        status=response.status_code,
                        execution_id=execution.id,
                        attempt=attempt.retry_state.attempt_number,
                    )
        except RetryError as e:
            raise SlackDeliveryError("Slack delivery failed after retries") from e


class SlackDeliveryError(RuntimeError):
    pass
