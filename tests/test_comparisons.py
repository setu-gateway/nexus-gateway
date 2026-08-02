import time
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from conftest import register_and_login
from fastapi.testclient import TestClient

from apps.gateway.comparison import run_comparison
from apps.gateway.main import app
from apps.gateway.providers.instance import model_registry
from apps.gateway.providers.registry import ProviderRegistry

client = TestClient(app)


def _request_with_lock_retry(fn, *, attempts=5, initial_delay=0.05):
    """See tests/test_evaluation.py's copy of this helper."""
    delay = initial_delay
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as e:
            if "locked" not in str(e).lower() or attempt == attempts - 1:
                raise
            time.sleep(delay)
            delay *= 2


def _response(text: str, usage=None) -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5},
    }


class _FakeProvider:
    def __init__(self, name, response=None, error=None):
        self.provider_name = name
        self.name = name
        self._response = response or _response(f"{name} says hi")
        self._error = error

    async def chat(self, request):
        if self._error:
            raise self._error
        return self._response


# ---------------------------------------------------------------------------
# Service layer (direct, no HTTP)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_comparison_returns_enriched_results_in_requested_order():
    registry = ProviderRegistry()
    registry.register_provider(_FakeProvider("openai", response=_response("openai answer")), enabled=True)
    registry.register_provider(_FakeProvider("anthropic", response=_response("anthropic answer")), enabled=True)

    results = await run_comparison(registry, model_registry, ["gpt-4o", "claude-3-5-sonnet"], [{"role": "user", "content": "hi"}])

    assert [r.model for r in results] == ["gpt-4o", "claude-3-5-sonnet"]
    assert results[0].response_text == "openai answer"
    assert results[1].response_text == "anthropic answer"
    assert results[0].provider == "openai"
    assert results[1].provider == "anthropic"


@pytest.mark.asyncio
async def test_run_comparison_computes_cost_from_usage():
    registry = ProviderRegistry()
    registry.register_provider(
        _FakeProvider("openai", response=_response("hi", usage={"prompt_tokens": 1000, "completion_tokens": 1000})),
        enabled=True,
    )

    results = await run_comparison(registry, model_registry, ["gpt-4o"], [{"role": "user", "content": "hi"}])

    # gpt-4o catalog pricing: $0.0025/1k input + $0.01/1k output -> 1k+1k tokens
    assert results[0].cost_usd == pytest.approx(0.0125, rel=1e-6)
    assert results[0].prompt_tokens == 1000
    assert results[0].completion_tokens == 1000


@pytest.mark.asyncio
async def test_run_comparison_captures_per_model_failure_without_raising():
    registry = ProviderRegistry()
    registry.register_provider(_FakeProvider("openai", response=_response("ok")), enabled=True)
    registry.register_provider(_FakeProvider("anthropic", error=RuntimeError("anthropic down")), enabled=True)

    results = await run_comparison(registry, model_registry, ["gpt-4o", "claude-3-5-sonnet"], [{"role": "user", "content": "hi"}])

    by_model = {r.model: r for r in results}
    assert by_model["gpt-4o"].success is True
    assert by_model["claude-3-5-sonnet"].success is False
    assert "anthropic down" in by_model["claude-3-5-sonnet"].error
    assert by_model["claude-3-5-sonnet"].cost_usd is None


@pytest.mark.asyncio
async def test_run_comparison_falls_back_to_openai_for_unlisted_model_ids():
    """model_registry.resolve_provider_model treats an unrecognized model id as an
    OpenAI model - run_comparison should follow that same, already-established
    convention rather than rejecting the id itself."""
    registry = ProviderRegistry()
    registry.register_provider(_FakeProvider("openai", response=_response("custom answer")), enabled=True)

    results = await run_comparison(registry, model_registry, ["my-custom-finetune"], [{"role": "user", "content": "hi"}])
    assert results[0].provider == "openai"
    assert results[0].upstream_model == "my-custom-finetune"
    assert results[0].response_text == "custom answer"


# ---------------------------------------------------------------------------
# API layer
# ---------------------------------------------------------------------------


def _create_org():
    org_id, headers = register_and_login(client)
    return {"id": org_id}, headers


def test_create_comparison_persists_run_and_results():
    # gemini, not anthropic, alongside openai: anthropic defaults to disabled in this
    # environment (apps/gateway/providers/instance.py), so a real (unmocked) call
    # through the live provider_registry singleton would legitimately fail for it.
    org, headers = _create_org()
    resp = client.post(
        "/comparisons",
        json={
            "organization_id": org["id"],
            "name": "gpt-4o vs gemini",
            "messages": [{"role": "user", "content": "What is 2+2?"}],
            "models": ["gpt-4o", "gemini-1.5-pro"],
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "gpt-4o vs gemini"
    assert len(body["results"]) == 2
    assert {r["model"] for r in body["results"]} == {"gpt-4o", "gemini-1.5-pro"}
    for r in body["results"]:
        assert r["success"] is True
        assert r["response_text"]


def test_create_comparison_requires_at_least_two_models():
    org, headers = _create_org()
    resp = client.post(
        "/comparisons",
        json={"organization_id": org["id"], "messages": [{"role": "user", "content": "hi"}], "models": ["gpt-4o"]},
        headers=headers,
    )
    assert resp.status_code == 422


def test_create_comparison_rejects_duplicate_models():
    org, headers = _create_org()
    resp = client.post(
        "/comparisons",
        json={
            "organization_id": org["id"],
            "messages": [{"role": "user", "content": "hi"}],
            "models": ["gpt-4o", "gpt-4o"],
        },
        headers=headers,
    )
    assert resp.status_code == 422


def test_create_comparison_rejects_message_missing_role_or_content():
    org, headers = _create_org()
    resp = client.post(
        "/comparisons",
        json={
            "organization_id": org["id"],
            "messages": [{"role": "user"}],
            "models": ["gpt-4o", "gemini-1.5-pro"],
        },
        headers=headers,
    )
    assert resp.status_code == 422


def test_list_comparisons_scoped_to_organization():
    org_a, headers_a = _create_org()
    org_b, headers_b = _create_org()
    client.post(
        "/comparisons",
        json={"organization_id": org_a["id"], "messages": [{"role": "user", "content": "hi"}], "models": ["gpt-4o", "gemini-1.5-pro"]},
        headers=headers_a,
    )
    client.post(
        "/comparisons",
        json={"organization_id": org_b["id"], "messages": [{"role": "user", "content": "hi"}], "models": ["gpt-4o", "gemini-1.5-pro"]},
        headers=headers_b,
    )
    listed = client.get("/comparisons", params={"organization_id": org_a["id"]}, headers=headers_a).json()
    assert len(listed) == 1
    # List is summary-only - no full messages/results payload.
    assert "results" not in listed[0]


def test_get_comparison_returns_full_detail():
    org, headers = _create_org()
    created = client.post(
        "/comparisons",
        json={"organization_id": org["id"], "messages": [{"role": "user", "content": "hi"}], "models": ["gpt-4o", "gemini-1.5-pro"]},
        headers=headers,
    ).json()

    fetched = client.get(f"/comparisons/{created['id']}", headers=headers).json()
    assert fetched["id"] == created["id"]
    assert len(fetched["results"]) == 2
    assert fetched["messages"] == [{"role": "user", "content": "hi"}]


def test_get_comparison_404_for_unknown_id():
    _, headers = _create_org()
    assert client.get(f"/comparisons/{uuid.uuid4()}", headers=headers).status_code == 404


def test_delete_comparison():
    org, headers = _create_org()
    created = client.post(
        "/comparisons",
        json={"organization_id": org["id"], "messages": [{"role": "user", "content": "hi"}], "models": ["gpt-4o", "gemini-1.5-pro"]},
        headers=headers,
    ).json()

    # create_comparison fires an audit write via fire_and_forget - see
    # test_evaluation.py's test_delete_eval_suite for why this is retried.
    resp = _request_with_lock_retry(lambda: client.delete(f"/comparisons/{created['id']}", headers=headers))
    assert resp.status_code == 200
    assert client.get(f"/comparisons/{created['id']}", headers=headers).status_code == 404


def test_create_comparison_records_provider_failure_without_failing_the_request():
    org, headers = _create_org()
    with patch(
        "plugins.providers.openai.plugin.OpenAIProviderPlugin.chat",
        new_callable=AsyncMock,
        side_effect=RuntimeError("boom"),
    ):
        resp = client.post(
            "/comparisons",
            json={"organization_id": org["id"], "messages": [{"role": "user", "content": "hi"}], "models": ["gpt-4o", "gemini-1.5-pro"]},
            headers=headers,
        )
    assert resp.status_code == 201
    by_model = {r["model"]: r for r in resp.json()["results"]}
    assert by_model["gpt-4o"]["success"] is False
    assert "boom" in by_model["gpt-4o"]["error"]
    assert by_model["gemini-1.5-pro"]["success"] is True
