import json
from unittest.mock import AsyncMock, patch

from conftest import register_and_login
from fastapi.testclient import TestClient

from apps.gateway.cache.keys import compute_cache_key
from apps.gateway.main import app

client = TestClient(app)


def test_compute_cache_key_is_deterministic_regardless_of_dict_order():
    messages = [{"role": "user", "content": "hi"}]
    key1 = compute_cache_key("openai", "gpt-4o", messages, 0.7, 1.0, None)
    key2 = compute_cache_key("OPENAI", "gpt-4o", messages, 0.7, 1.0, None)
    assert key1 == key2  # provider casing shouldn't matter


def test_compute_cache_key_differs_on_any_component():
    base = compute_cache_key("openai", "gpt-4o", [{"role": "user", "content": "hi"}], 0.7, 1.0, None)
    assert base != compute_cache_key("openai", "gpt-4o", [{"role": "user", "content": "hi"}], 0.9, 1.0, None)
    assert base != compute_cache_key("openai", "gpt-4o", [{"role": "user", "content": "bye"}], 0.7, 1.0, None)
    assert base != compute_cache_key("gemini", "gpt-4o", [{"role": "user", "content": "hi"}], 0.7, 1.0, None)


def test_identical_chat_completion_is_served_from_cache():
    payload = {"model": "gpt-4o", "messages": [{"role": "user", "content": "cache me please"}], "temperature": 0.7}

    with patch("plugins.providers.openai.plugin.OpenAIProviderPlugin.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.return_value = {
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "model": "gpt-4o",
            "choices": [{"message": {"role": "assistant", "content": "hello"}}],
        }
        first = client.post("/v1/chat/completions", json=payload)
        assert first.status_code == 200
        assert mock_chat.call_count == 1

        second = client.post("/v1/chat/completions", json=payload)
        assert second.status_code == 200
        assert mock_chat.call_count == 1  # not called again - served from cache
        assert second.json()["choices"][0]["message"]["content"] == "hello"


def test_cache_hit_is_recorded_in_analytics_with_zero_cost():
    payload = {"model": "gpt-4o", "messages": [{"role": "user", "content": "track my cache hits"}]}
    client.post("/v1/chat/completions", json=payload)
    client.post("/v1/chat/completions", json=payload)

    rows = client.get("/analytics/requests").json()
    cache_hit_rows = [r for r in rows if r["cache_hit"]]
    assert len(cache_hit_rows) >= 1
    assert cache_hit_rows[0]["estimated_cost"] == 0.0


def test_different_temperature_is_a_cache_miss():
    with patch("plugins.providers.openai.plugin.OpenAIProviderPlugin.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.return_value = {
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "model": "gpt-4o",
            "choices": [{"message": {"role": "assistant", "content": "hi"}}],
        }
        client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "vary me"}], "temperature": 0.2},
        )
        client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "vary me"}], "temperature": 0.9},
        )
        assert mock_chat.call_count == 2


def test_streaming_response_is_cached_and_replayed():
    payload = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "stream me and cache me"}],
        "stream": True,
    }

    def _fake_stream_chat(*args, **kwargs):
        # A fresh async generator per call, mirroring OpenAIProviderPlugin.chat()
        # returning self.stream_chat(request) unstarted - a plain AsyncMock return_value
        # would be exhausted (and unusable) after the first request consumed it.
        async def _gen():
            event = {
                "id": "chatcmpl-1",
                "object": "chat.completion.chunk",
                "model": "gpt-4o",
                "choices": [{"index": 0, "delta": {"content": "hello"}, "finish_reason": "stop"}],
            }
            yield f"data: {json.dumps(event)}\n\n"
            yield "data: [DONE]\n\n"

        return _gen()

    with patch("plugins.providers.openai.plugin.OpenAIProviderPlugin.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.side_effect = _fake_stream_chat

        first = client.post("/v1/chat/completions", json=payload)
        assert first.status_code == 200
        assert mock_chat.call_count == 1
        assert "data: " in first.text
        assert "[DONE]" in first.text
        assert "hello" in first.text

        second = client.post("/v1/chat/completions", json=payload)
        assert second.status_code == 200
        assert mock_chat.call_count == 1  # not called again - served from cache
        assert "data: " in second.text
        assert "[DONE]" in second.text
        assert "hello" in second.text


def test_cache_disabled_for_project_bypasses_cache():
    org_id, headers = register_and_login(client)
    project = client.post("/projects", json={"name": "No Cache Project", "organization_id": org_id}, headers=headers).json()
    key = client.post("/keys", json={"project_id": project["id"], "name": "k"}, headers=headers).json()

    resp = client.put("/cache/policy", json={"project_id": project["id"], "enabled": False, "ttl_seconds": 60}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False

    payload = {"model": "gpt-4o", "messages": [{"role": "user", "content": "no cache for me"}]}
    headers = {"Authorization": f"Bearer {key['key']}"}
    with patch("plugins.providers.openai.plugin.OpenAIProviderPlugin.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.return_value = {
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "model": "gpt-4o",
            "choices": [{"message": {"role": "assistant", "content": "fresh"}}],
        }
        client.post("/v1/chat/completions", json=payload, headers=headers)
        client.post("/v1/chat/completions", json=payload, headers=headers)
        assert mock_chat.call_count == 2  # policy disabled -> always calls the provider


def test_cache_clear_removes_entries():
    _, headers = register_and_login(client)
    payload = {"model": "gpt-4o", "messages": [{"role": "user", "content": "clear me later"}]}
    client.post("/v1/chat/completions", json=payload)

    stats_before = client.get("/cache/stats", headers=headers).json()
    assert stats_before["total_entries"] >= 1

    # Clearing every project's cache (no project_id) requires Role.OWNER, which
    # registering grants.
    clear_resp = client.delete("/cache", headers=headers)
    assert clear_resp.status_code == 200
    assert clear_resp.json()["cleared_entries"] >= 1

    stats_after = client.get("/cache/stats", headers=headers).json()
    assert stats_after["total_entries"] == 0


def test_cache_policy_defaults_when_no_project():
    _, headers = register_and_login(client)
    resp = client.get("/cache/policy", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is True
    assert data["ttl_seconds"] == 3600
