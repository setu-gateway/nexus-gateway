from unittest.mock import AsyncMock, patch

from conftest import register_and_login
from fastapi.testclient import TestClient

from apps.gateway.main import app

client = TestClient(app)


def test_time_machine_not_recorded_without_opt_in_header():
    org_id, headers = register_and_login(client)
    payload = {"model": "gpt-4o", "messages": [{"role": "user", "content": "no time machine"}]}
    resp = client.post("/v1/chat/completions", json=payload, headers={"X-Setu-Organization-Id": org_id})
    assert resp.status_code == 200

    rows = client.get("/time-machine", headers=headers).json()
    assert not any(r["request_messages"] == payload["messages"] for r in rows)


def test_time_machine_records_opted_in_request():
    org_id, headers = register_and_login(client)
    payload = {"model": "gpt-4o", "messages": [{"role": "user", "content": "remember this one"}]}
    resp = client.post("/v1/chat/completions", json=payload, headers={"X-Setu-Organization-Id": org_id, "X-Setu-Time-Machine": "true"})
    assert resp.status_code == 200

    rows = client.get("/time-machine", headers=headers).json()
    match = next(r for r in rows if r["request_messages"] == payload["messages"])
    assert match["provider"] == "openai"
    assert match["requested_model"] == "gpt-4o"

    get_resp = client.get(f"/time-machine/{match['request_id']}", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["response_body"]["choices"][0]["message"]["content"]


def test_time_machine_replay_against_same_provider():
    org_id, headers = register_and_login(client)
    payload = {"model": "gpt-4o", "messages": [{"role": "user", "content": "replay me"}]}
    client.post("/v1/chat/completions", json=payload, headers={"X-Setu-Organization-Id": org_id, "X-Setu-Time-Machine": "true"})
    request_id = next(
        r["request_id"] for r in client.get("/time-machine", headers=headers).json() if r["request_messages"] == payload["messages"]
    )

    replay_resp = client.post(f"/time-machine/{request_id}/replay", headers=headers)
    assert replay_resp.status_code == 200
    data = replay_resp.json()
    assert data["original"]["provider"] == "openai"
    assert data["replayed"]["provider"] == "openai"
    assert data["replayed"]["success"] is True
    assert "diff_ratio" in data


def test_time_machine_replay_against_different_provider():
    org_id, headers = register_and_login(client)
    payload = {"model": "gpt-4o", "messages": [{"role": "user", "content": "compare providers"}]}
    client.post("/v1/chat/completions", json=payload, headers={"X-Setu-Organization-Id": org_id, "X-Setu-Time-Machine": "true"})
    request_id = next(
        r["request_id"] for r in client.get("/time-machine", headers=headers).json() if r["request_messages"] == payload["messages"]
    )

    replay_resp = client.post(f"/time-machine/{request_id}/replay", params={"provider": "gemini"}, headers=headers)
    assert replay_resp.status_code == 200
    data = replay_resp.json()
    assert data["replayed"]["provider"] == "gemini"
    assert data["replayed"]["upstream_model"] != data["original"]["upstream_model"]


def test_time_machine_replay_reports_failure_without_crashing():
    org_id, headers = register_and_login(client)
    payload = {"model": "gpt-4o", "messages": [{"role": "user", "content": "will fail on replay"}]}
    client.post("/v1/chat/completions", json=payload, headers={"X-Setu-Organization-Id": org_id, "X-Setu-Time-Machine": "true"})
    request_id = next(
        r["request_id"] for r in client.get("/time-machine", headers=headers).json() if r["request_messages"] == payload["messages"]
    )

    with patch("plugins.providers.openai.plugin.OpenAIProviderPlugin.chat", side_effect=RuntimeError("replay boom")):
        replay_resp = client.post(f"/time-machine/{request_id}/replay", headers=headers)
    assert replay_resp.status_code == 200
    data = replay_resp.json()
    assert data["replayed"]["success"] is False
    assert "replay boom" in data["replayed"]["error"]


def test_time_machine_get_unknown_request_id_404s():
    _, headers = register_and_login(client)
    assert client.get("/time-machine/not-a-real-id", headers=headers).status_code == 404


def test_time_machine_streaming_request_is_captured():
    # The write happens via asyncio.create_task after the SSE generator drains, so
    # waiting on it via a real DB round-trip would race the test's own DB fixture
    # teardown. Scheduling a task still calls record_time_machine_entry(...)
    # synchronously to produce its coroutine, so patching it lets us assert the
    # capture was scheduled with the right data without depending on when it runs.
    payload = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "stream and remember"}],
        "stream": True,
    }
    with patch("apps.gateway.api.openai_v1.record_time_machine_entry", new_callable=AsyncMock) as mock_record:
        resp = client.post("/v1/chat/completions", json=payload, headers={"X-Setu-Time-Machine": "true"})
        assert resp.status_code == 200

    mock_record.assert_called_once()
    kwargs = mock_record.call_args.kwargs
    assert kwargs["request_messages"] == payload["messages"]
    assert kwargs["provider"] == "openai"
    assert kwargs["requested_model"] == "gpt-4o"
