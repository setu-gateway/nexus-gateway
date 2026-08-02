import uuid
from unittest.mock import patch

import pytest
from conftest import register_and_login
from fastapi.testclient import TestClient

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


def test_analytics_requests_and_summary_filter_by_project():
    org_id, headers = register_and_login(client)
    project = client.post("/projects", json={"name": "Analytics Project", "organization_id": org_id}, headers=headers).json()
    other_project = client.post("/projects", json={"name": "Other Project", "organization_id": org_id}, headers=headers).json()
    key = client.post("/keys", json={"project_id": project["id"], "name": "analytics key"}, headers=headers).json()

    client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "project scoped"}]},
        headers={"Authorization": f"Bearer {key['key']}"},
    )

    scoped_rows = client.get("/analytics/requests", params={"project_id": project["id"]}).json()
    assert len(scoped_rows) == 1
    assert scoped_rows[0]["project_id"] == project["id"]

    other_rows = client.get("/analytics/requests", params={"project_id": other_project["id"]}).json()
    assert other_rows == []

    summary = client.get("/analytics/summary", params={"project_id": project["id"]}).json()
    assert summary["total_requests"] == 1


def test_analytics_requests_and_summary_filter_by_model():
    client.post("/v1/chat/completions", json={"model": "gpt-4o", "messages": [{"role": "user", "content": "model a"}]})
    client.post("/v1/chat/completions", json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "model b"}]})

    rows = client.get("/analytics/requests", params={"model": "gpt-4o-mini"}).json()
    assert rows and all(r["requested_model"] == "gpt-4o-mini" for r in rows)

    summary = client.get("/analytics/summary", params={"model": "gpt-4o-mini"}).json()
    assert summary["total_requests"] == len(rows)
    assert all(m["model"] == "gpt-4o-mini" for m in summary["top_models"])


def test_analytics_summary_top_models_breakdown():
    client.post("/v1/chat/completions", json={"model": "gpt-4o", "messages": [{"role": "user", "content": "top models 1"}]})
    client.post("/v1/chat/completions", json={"model": "gpt-4o", "messages": [{"role": "user", "content": "top models 2"}]})
    client.post("/v1/chat/completions", json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "top models 3"}]})

    summary = client.get("/analytics/summary").json()
    by_model = {m["model"]: m for m in summary["top_models"]}
    assert by_model["gpt-4o"]["requests"] >= 2
    assert by_model["gpt-4o-mini"]["requests"] >= 1
    # Sorted descending by request count.
    assert summary["top_models"] == sorted(summary["top_models"], key=lambda m: m["requests"], reverse=True)


def test_analytics_summary_top_models_limit_is_respected():
    for model in ["gpt-4o", "gpt-4o-mini", "claude-3-5-sonnet", "gemini-1.5-pro"]:
        client.post("/v1/chat/completions", json={"model": model, "messages": [{"role": "user", "content": "limit test"}]})

    summary = client.get("/analytics/summary", params={"top_models_limit": 2}).json()
    assert len(summary["top_models"]) <= 2
