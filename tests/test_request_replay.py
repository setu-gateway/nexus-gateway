from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest

from apps.gateway.main import app
from apps.gateway.providers.registry import ProviderRegistry
from apps.gateway.routing.replay import replay_request

client = TestClient(app)


class _FakeProvider:
    def __init__(self, name, response=None, error=None):
        self.provider_name = name
        self.name = name
        self._response = response or {"choices": [{"message": {"content": f"{name} says hi"}}]}
        self._error = error

    async def chat(self, request):
        if self._error:
            raise self._error
        return self._response


@pytest.mark.asyncio
async def test_replay_request_runs_all_candidates_independently():
    registry = ProviderRegistry()
    registry.register_provider(_FakeProvider("openai"), enabled=True)
    registry.register_provider(_FakeProvider("gemini", error=RuntimeError("gemini down")), enabled=True)

    results = await replay_request(
        registry,
        [("openai", "gpt-4o"), ("gemini", "gemini-1.5-pro")],
        messages=[{"role": "user", "content": "hi"}],
    )

    by_provider = {r.provider: r for r in results}
    assert by_provider["openai"].success is True
    assert by_provider["openai"].response["choices"][0]["message"]["content"] == "openai says hi"
    assert by_provider["gemini"].success is False
    assert "gemini down" in by_provider["gemini"].error


@pytest.mark.asyncio
async def test_replay_request_reports_missing_provider_without_raising():
    registry = ProviderRegistry()
    results = await replay_request(registry, [("openai", "gpt-4o")], messages=[{"role": "user", "content": "hi"}])
    assert results[0].success is False
    assert "not enabled" in results[0].error


def test_replay_endpoint_resolves_candidates_from_model():
    resp = client.post(
        "/routing/replay",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "compare me"}]},
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    providers = {r["provider"] for r in results}
    assert "openai" in providers  # primary candidate for gpt-4o always included
    assert all(r["latency_ms"] >= 0 for r in results)


def test_replay_endpoint_with_explicit_providers():
    resp = client.post(
        "/routing/replay",
        json={
            "providers": ["openai", "ollama"],
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert resp.status_code == 200
    providers = {r["provider"] for r in resp.json()["results"]}
    assert providers == {"openai", "ollama"}


def test_replay_endpoint_requires_model_or_providers():
    resp = client.post("/routing/replay", json={"messages": [{"role": "user", "content": "hi"}]})
    assert resp.status_code == 400


def test_replay_endpoint_one_provider_failing_does_not_block_others():
    with patch("plugins.providers.openai.plugin.OpenAIProviderPlugin.chat", side_effect=RuntimeError("boom")):
        resp = client.post(
            "/routing/replay",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert resp.status_code == 200
    by_provider = {r["provider"]: r for r in resp.json()["results"]}
    assert by_provider["openai"]["success"] is False
    # At least one other candidate (e.g. gemini) should have succeeded independently.
    assert any(r["success"] for name, r in by_provider.items() if name != "openai")


def test_replay_is_not_recorded_to_analytics():
    before = client.get("/analytics/summary").json()["total_requests"]
    client.post("/routing/replay", json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]})
    after = client.get("/analytics/summary").json()["total_requests"]
    assert after == before
