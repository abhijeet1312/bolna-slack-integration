"""Shared pytest fixtures."""

import os

import pytest

# Set required env BEFORE importing the app
os.environ.setdefault("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/X")
os.environ.setdefault("ALLOWED_IPS", "")  # disable IP check in tests
os.environ.setdefault("WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("REDIS_URL", "redis://invalid-host:1/0")  # forces memory fallback
os.environ.setdefault("LOG_LEVEL", "WARNING")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
