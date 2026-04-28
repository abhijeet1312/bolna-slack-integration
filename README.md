# Bolna → Slack Integration (Production)

A FastAPI service that listens for [Bolna](https://www.bolna.ai) call webhooks and posts
a Slack alert whenever a call ends, containing **id, agent_id, duration, and transcript**.

## Features

- ✅ FastAPI + Gunicorn/Uvicorn workers
- ✅ Redis-backed dedupe (atomic `SET NX EX`) — no double-alerts on retries
- ✅ Background task processing — webhook returns 200 in < 5ms
- ✅ Slack delivery with exponential-backoff retries (`tenacity`)
- ✅ Shared-secret auth (header or query param) + IP whitelist
- ✅ Rate limiting via `slowapi`
- ✅ Structured JSON logs with request IDs (`structlog`)
- ✅ Pydantic-validated payloads
- ✅ `/healthz` (liveness) and `/readyz` (readiness with Redis check)
- ✅ Multi-stage Dockerfile, non-root user, healthcheck
- ✅ docker-compose with Redis
- ✅ Pytest suite + GitHub Actions CI

## Architecture

```
Bolna → POST /webhook (auth + IP check + rate limit)
         → return 200 immediately
         → BackgroundTask:
             ├─ skip if status not terminal
             ├─ Redis SET NX EX → skip if duplicate
             └─ Slack POST (3 retries, exp backoff)
```

## Quick start (Docker)

```bash
git clone <this-repo> bolna-slack && cd bolna-slack
cp .env.example .env
# Edit .env — set SLACK_WEBHOOK_URL and WEBHOOK_SECRET
docker compose up -d
curl http://localhost:8000/healthz
```

Expose to Bolna with ngrok / Cloudflare Tunnel / your LB:

```bash
ngrok http 8000
```

Then in Bolna's **Analytics tab**, set the webhook URL to:

```
https://<your-public-host>/webhook?token=<WEBHOOK_SECRET>
```

## Quick start (local dev, no Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env  # edit it
make dev              # uvicorn with reload, falls back to in-memory dedupe if no Redis
```

## Configuration

All via env vars (see `.env.example`).

| Variable                  | Required | Default            | Description                                      |
|---------------------------|----------|--------------------|--------------------------------------------------|
| `SLACK_WEBHOOK_URL`       | yes      | —                  | Slack Incoming Webhook URL                       |
| `WEBHOOK_SECRET`          | rec.     | —                  | Shared secret; clients send via `?token=` or header |
| `ALLOWED_IPS`             | rec.     | `13.203.39.153`    | CSV of source IPs. Empty disables.               |
| `TRUST_FORWARDED_FOR`     | no       | `false`            | Set `true` behind a proxy/LB                     |
| `REDIS_URL`               | no       | `redis://redis:6379/0` | Falls back to in-memory if unreachable      |
| `DEDUPE_TTL_SECONDS`      | no       | `86400`            | How long an execution ID stays "alerted"         |
| `SLACK_MAX_RETRIES`       | no       | `3`                | Retry attempts for Slack delivery                |
| `RATE_LIMIT_PER_MINUTE`   | no       | `120`              | Per-IP rate limit on `/webhook`                  |
| `LOG_LEVEL`               | no       | `INFO`             |                                                  |
| `WEB_CONCURRENCY`         | no       | `2`                | Gunicorn worker count                            |

## Endpoints

| Method | Path        | Purpose                                           |
|--------|-------------|---------------------------------------------------|
| GET    | `/healthz`  | Liveness — always 200 if process is up            |
| GET    | `/readyz`   | Readiness — 503 if Redis is configured but down   |
| POST   | `/webhook`  | Receives Bolna execution payloads                 |

## Testing the webhook

```bash
curl -X POST "http://localhost:8000/webhook?token=<WEBHOOK_SECRET>" \
  -H 'Content-Type: application/json' \
  -d '{
    "id": "test-exec-123",
    "agent_id": "d311e737-70e6-4075-bef6-c0ef3a7026b4",
    "status": "completed",
    "transcript": "agent: Hi!\nuser: Hello!\nagent: Goodbye.",
    "telephony_data": {"duration": 42}
  }'
# → {"received":true}
```

A formatted message will land in Slack within ~100ms.

## Running tests

```bash
make test
# or:
pytest
```

## Deployment

### Cloud Run / Fly.io / Render / Railway

These all consume the `Dockerfile` directly. Set env vars in the platform's
secrets manager. Set `TRUST_FORWARDED_FOR=true` since they sit behind a proxy.

### Kubernetes

Use `/healthz` for `livenessProbe` and `/readyz` for `readinessProbe`. Run at
least 2 replicas; Redis is shared so dedupe works across replicas.

```yaml
livenessProbe:
  httpGet: { path: /healthz, port: 8000 }
  periodSeconds: 30
readinessProbe:
  httpGet: { path: /readyz, port: 8000 }
  periodSeconds: 10
```

### Behind a load balancer

- Set `TRUST_FORWARDED_FOR=true` so client IPs come from `X-Forwarded-For`.
- Whitelist Bolna's IP (`13.203.39.153`) at the LB layer too if possible.

## Production hardening checklist

- [ ] `SLACK_WEBHOOK_URL` stored in a secrets manager (not committed)
- [ ] `WEBHOOK_SECRET` is ≥ 32 random bytes (`python -c "import secrets; print(secrets.token_urlsafe(32))"`)
- [ ] `ALLOWED_IPS` set, `TRUST_FORWARDED_FOR` matches your topology
- [ ] Redis has persistence (`appendonly yes`) and backups
- [ ] At least 2 app replicas behind an LB
- [ ] Logs shipped to your aggregator (CloudWatch / Datadog / Loki)
- [ ] Alarms on log lines with `level=error` (especially `alert_failed`)

## Project layout

```
bolna-slack/
├── app/
│   ├── main.py            # FastAPI app, routes, lifespan, background tasks
│   ├── config.py          # Pydantic settings
│   ├── models.py          # BolnaExecution payload model
│   ├── slack_client.py    # Slack sender with retries
│   ├── dedupe.py          # Redis + in-memory dedupe stores
│   ├── security.py        # IP whitelist + token verify
│   └── logging_config.py  # structlog setup
├── tests/
│   ├── test_webhook.py
│   └── test_slack_client.py
├── .github/workflows/ci.yml
├── Dockerfile             # multi-stage, non-root, healthcheck
├── docker-compose.yml     # app + redis
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
├── Makefile
├── .env.example
└── README.md
```

## License

MIT
