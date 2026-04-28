"""Application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Service ---
    app_name: str = "bolna-slack-integration"
    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")
    port: int = Field(default=8000)

    # --- Slack ---
    slack_webhook_url: SecretStr = Field(...)
    slack_request_timeout: float = Field(default=10.0)
    slack_max_retries: int = Field(default=3)

    # --- Bolna webhook security ---
    # A shared secret the webhook caller must include as ?token=... or
    # X-Webhook-Token header. Bolna lets you embed query params in the URL.
    webhook_secret: SecretStr | None = Field(default=None)
    # Comma-separated list of allowed source IPs (Bolna publishes 13.203.39.153).
    # Empty / unset disables the IP check (useful for tests).
    allowed_ips: str = Field(default="13.203.39.153")
    # If true, trust X-Forwarded-For (set this when behind a load balancer/proxy).
    trust_forwarded_for: bool = Field(default=False)

    # --- Redis (for dedupe & rate limit) ---
    redis_url: str = Field(default="redis://redis:6379/0")
    dedupe_ttl_seconds: int = Field(default=86400)  # 24h

    # --- Rate limiting ---
    rate_limit_per_minute: int = Field(default=120)


@lru_cache
def get_settings() -> Settings:
    return Settings()
