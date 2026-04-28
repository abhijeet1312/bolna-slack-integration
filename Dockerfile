# syntax=docker/dockerfile:1.7

# ---- Builder ----
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
COPY requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt

# ---- Runtime ----
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Non-root user
RUN groupadd --system --gid 1001 app && \
    useradd  --system --uid 1001 --gid app --no-create-home app

WORKDIR /app

# Install deps from prebuilt wheels (much faster, no build toolchain in final image)
COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-index --find-links=/wheels -r requirements.txt && rm -rf /wheels

COPY app/ ./app/

USER app

EXPOSE 8000

# Production server: gunicorn with uvicorn workers
# Workers default to 2 — override with WEB_CONCURRENCY env var
ENV WEB_CONCURRENCY=2
CMD ["sh", "-c", "exec gunicorn app.main:app \
    --bind 0.0.0.0:${PORT:-8000} \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers ${WEB_CONCURRENCY} \
    --access-logfile - \
    --error-logfile - \
    --timeout 30 \
    --graceful-timeout 30 \
    --keep-alive 5"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; \
                   sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz').status==200 else 1)" \
        || exit 1
