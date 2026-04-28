"""End-to-end tests for the webhook flow."""

from unittest.mock import AsyncMock

import pytest

from app.slack_client import SlackClient


@pytest.fixture(autouse=True)
def mock_slack(monkeypatch):
    """Replace SlackClient.send with a mock for all tests."""
    mock = AsyncMock()
    monkeypatch.setattr(SlackClient, "send", mock)
    return mock


def _payload(**overrides):
    base = {
        "id": "exec-123",
        "agent_id": "agent-abc",
        "status": "completed",
        "transcript": "agent: Hi\nuser: Hello\nagent: Goodbye",
        "telephony_data": {"duration": 42},
    }
    base.update(overrides)
    return base


def test_health(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_readyz_with_memory_fallback(client):
    r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json()["ready"] is True


def test_webhook_requires_token(client):
    r = client.post("/webhook", json=_payload())
    assert r.status_code == 401


def test_webhook_rejects_wrong_token(client):
    r = client.post(
        "/webhook", json=_payload(), headers={"X-Webhook-Token": "wrong"}
    )
    assert r.status_code == 401


def test_webhook_accepts_token_in_query(client, mock_slack):
    r = client.post("/webhook?token=test-secret", json=_payload())
    assert r.status_code == 200
    assert r.json() == {"received": True}
    mock_slack.assert_awaited_once()


def test_webhook_accepts_token_in_header(client, mock_slack):
    r = client.post(
        "/webhook", json=_payload(), headers={"X-Webhook-Token": "test-secret"}
    )
    assert r.status_code == 200
    mock_slack.assert_awaited_once()


def test_webhook_skips_non_terminal(client, mock_slack):
    r = client.post(
        "/webhook?token=test-secret", json=_payload(status="in-progress")
    )
    assert r.status_code == 200
    mock_slack.assert_not_awaited()


def test_webhook_dedupes_same_id(client, mock_slack):
    payload = _payload(id="dedupe-me")
    r1 = client.post("/webhook?token=test-secret", json=payload)
    r2 = client.post("/webhook?token=test-secret", json=payload)
    assert r1.status_code == r2.status_code == 200
    # Slack send should only have been called once despite two webhook hits
    assert mock_slack.await_count == 1


def test_webhook_validates_payload(client):
    r = client.post(
        "/webhook?token=test-secret", json={"id": "no-agent-or-status"}
    )
    assert r.status_code == 422


def test_webhook_handles_invalid_json(client):
    r = client.post(
        "/webhook?token=test-secret",
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400


@pytest.mark.parametrize(
    "status_value",
    ["completed", "failed", "no-answer", "busy", "canceled"],
)
def test_all_terminal_statuses_alert(client, mock_slack, status_value):
    r = client.post(
        "/webhook?token=test-secret",
        json=_payload(id=f"id-{status_value}", status=status_value),
    )
    assert r.status_code == 200
    assert mock_slack.await_count >= 1


def test_call_disconnected_does_not_alert(client, mock_slack):
    """call-disconnected arrives before 'completed' with stale duration=0;
    we wait for 'completed' instead."""
    r = client.post(
        "/webhook?token=test-secret",
        json=_payload(id="disconnected-1", status="call-disconnected"),
    )
    assert r.status_code == 200
    assert mock_slack.await_count == 0

