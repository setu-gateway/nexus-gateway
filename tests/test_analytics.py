from unittest.mock import patch
import uuid

from fastapi.testclient import TestClient
import pytest

from apps.gateway.analytics import RequestTimeline, record_request
from apps.gateway.db.models import RequestLog
from apps.gateway.main import app

client = TestClient(app)


def test_request_timeline_marks_stages_in_increasing_order():
    timeline = RequestTimeline()
    timeline.mark("routed")
    timeline.mark("completed")

    stages = timeline.as_dict()
    assert "received" in stages
    assert "routed" in stages
    assert "completed" in stages
    assert stages["received"] <= stages["routed"] <= stages["completed"]
    assert timeline.total_ms >= stages["completed"]


@pytest.mark.asyncio
async def test_record_request_persists_a_queryable_row(db_session):
    timeline = RequestTimeline()
    timeline.mark("completed")
    request_id = str(uuid.uuid4())

    await record_request(
        request_id=request_id,
        requested_model="gpt-4o",
        status="success",
        timeline=timeline,
        selected_provider="openai",
        routing_policy="highest_availability",
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        estimated_cost=0.001,
    )

    from sqlalchemy import select

    result = await db_session.execute(select(RequestLog).where(RequestLog.request_id == request_id))
    row = result.scalar_one()
    assert row.requested_model == "gpt-4o"
    assert row.selected_provider == "openai"
    assert row.total_tokens == 15
    assert row.timeline is not None and "completed" in row.timeline


@pytest.mark.asyncio
async def test_record_request_never_raises_on_bad_input():
    timeline = RequestTimeline()
    # organization_id is not a valid UUID - should log and swallow, not raise.
    await record_request(
        request_id=str(uuid.uuid4()),
        requested_model="gpt-4o",
        status="success",
        timeline=timeline,
        organization_id="not-a-uuid",
    )


def test_chat_completion_writes_analytics_row_queryable_via_api():
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "log me"}]},
    )
    assert resp.status_code == 200

    list_resp = client.get("/analytics/requests", params={"status": "success"})
    assert list_resp.status_code == 200
    rows = list_resp.json()
    assert len(rows) >= 1
    assert any(r["requested_model"] == "gpt-4o" and r["selected_provider"] == "openai" for r in rows)


def test_chat_completion_failure_is_recorded_as_error():
    with (
        patch("plugins.providers.openai.plugin.OpenAIProviderPlugin.chat", side_effect=RuntimeError("down")),
        patch("plugins.providers.gemini.plugin.GeminiProviderPlugin.chat", side_effect=RuntimeError("also down")),
    ):
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "will fail"}]},
        )
    assert resp.status_code == 503

    error_rows = client.get("/analytics/requests", params={"status": "error"}).json()
    assert any(r["requested_model"] == "gpt-4o" and r["error_message"] for r in error_rows)


def test_analytics_summary_reflects_recorded_requests():
    client.post("/v1/chat/completions", json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]})

    summary = client.get("/analytics/summary").json()
    assert summary["total_requests"] >= 1
    assert summary["successful_requests"] >= 1
    assert summary["avg_latency_ms"] >= 0
    assert isinstance(summary["by_provider"], list)
    assert any(p["provider"] == "openai" for p in summary["by_provider"])


def test_analytics_requests_filters_by_organization():
    org_id = str(uuid.uuid4())
    client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "scoped"}]},
        headers={"X-Setu-Organization-Id": org_id},
    )

    scoped = client.get("/analytics/requests", params={"organization_id": org_id}).json()
    assert len(scoped) == 1
    assert scoped[0]["organization_id"] == org_id

    other_org = client.get("/analytics/requests", params={"organization_id": str(uuid.uuid4())}).json()
    assert other_org == []
