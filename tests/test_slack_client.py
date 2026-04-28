"""Unit tests for Slack payload building and helpers."""

from app.models import BolnaExecution, TelephonyData
from app.slack_client import build_payload, format_duration


def test_format_duration():
    assert format_duration(None) == "N/A"
    assert format_duration(0) == "0s"
    assert format_duration(45) == "45s"
    assert format_duration(60) == "1m 0s"
    assert format_duration(125) == "2m 5s"


def test_effective_duration_prefers_telephony():
    e = BolnaExecution(
        id="x",
        agent_id="y",
        status="completed",
        conversation_time=10,
        telephony_data=TelephonyData(duration=42),
    )
    assert e.effective_duration == 42


def test_effective_duration_falls_back_to_conversation_time():
    e = BolnaExecution(
        id="x", agent_id="y", status="completed", conversation_time=10
    )
    assert e.effective_duration == 10


def test_build_payload_structure():
    e = BolnaExecution(
        id="abc",
        agent_id="xyz",
        status="completed",
        transcript="hello world",
        telephony_data=TelephonyData(duration=125),
    )
    payload = build_payload(e)
    assert "blocks" in payload
    assert payload["text"].startswith("📞 Bolna call ended")
    # Find the field section
    fields_block = next(b for b in payload["blocks"] if b.get("type") == "section" and "fields" in b)
    field_texts = [f["text"] for f in fields_block["fields"]]
    assert any("abc" in t for t in field_texts)
    assert any("xyz" in t for t in field_texts)
    assert any("2m 5s" in t for t in field_texts)


def test_build_payload_handles_missing_transcript():
    e = BolnaExecution(id="abc", agent_id="xyz", status="completed")
    payload = build_payload(e)
    transcript_block = payload["blocks"][-1]
    assert "No transcript available" in transcript_block["text"]["text"]


def test_long_transcript_is_truncated():
    long_text = "x" * 5000
    e = BolnaExecution(id="a", agent_id="b", status="completed", transcript=long_text)
    payload = build_payload(e)
    transcript_text = payload["blocks"][-1]["text"]["text"]
    assert "truncated" in transcript_text
    assert len(transcript_text) < 3100
