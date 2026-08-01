from unittest.mock import AsyncMock, patch
import uuid

from fastapi.testclient import TestClient
import pytest

from apps.gateway.main import app

client = TestClient(app)


def test_v1_models_endpoint_includes_ollama_local_models():
    resp = client.get("/v1/models")
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "list"
    assert len(data["data"]) >= 5

    model_ids = [m["id"] for m in data["data"]]
    assert "gpt-4o" in model_ids
    assert "claude-3-5-sonnet" in model_ids
    assert any("llama" in m["id"].lower() for m in data["data"])


def test_v1_chat_completions_non_streaming():
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Hello Setu Gateway"}],
            "temperature": 0.5,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "chat.completion"
    assert data["model"] == "gpt-4o"
    assert len(data["choices"]) > 0


def test_v1_chat_completions_streaming():
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Stream response"}],
            "stream": True,
        },
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    text = resp.text
    assert "data: " in text
    assert "[DONE]" in text


def test_v1_embeddings_endpoint():
    resp = client.post(
        "/v1/embeddings",
        json={
            "model": "text-embedding-3-small",
            "input": "Vectorize this sentence for indexing",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "list"
    assert len(data["data"]) > 0
    assert "embedding" in data["data"][0]


def test_v1_chat_completions_validation_and_errors():
    no_msg = client.post("/v1/chat/completions", json={"model": "gpt-4o"})
    assert no_msg.status_code == 400

    no_input = client.post("/v1/embeddings", json={"model": "text-embedding-3-small"})
    assert no_input.status_code == 400


def test_v1_chat_completions_failover_on_provider_exception():
    """Epic 4.3: if the primary provider throws, the router retries a healthy
    same-tier equivalent instead of failing the whole request."""
    with patch(
        "plugins.providers.openai.plugin.OpenAIProviderPlugin.chat", side_effect=RuntimeError("Provider failed")
    ):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "Trigger failure"}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "chat.completion"
        # Served by the fallback's own upstream model, not the original openai one.
        assert data["model"] != "gpt-4o"


def test_v1_chat_completions_all_candidates_fail_returns_503():
    with (
        patch("plugins.providers.openai.plugin.OpenAIProviderPlugin.chat", side_effect=RuntimeError("openai down")),
        patch("plugins.providers.gemini.plugin.GeminiProviderPlugin.chat", side_effect=RuntimeError("gemini down")),
    ):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "Trigger total failure"}],
            },
        )
        assert resp.status_code == 503
        assert "All providers failed" in resp.json()["detail"]


def test_v1_chat_completions_debug_header_returns_routing_explanation():
    """Epic 4.8: X-Setu-Debug: true returns routing metadata via a response header,
    without altering the OpenAI-compatible response body shape."""
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Explain yourself, router"}],
        },
        headers={"X-Setu-Debug": "true"},
    )
    assert resp.status_code == 200
    assert "X-Setu-Routing-Debug" in resp.headers

    import json

    debug_payload = json.loads(resp.headers["X-Setu-Routing-Debug"])
    assert debug_payload["requested_model"] == "gpt-4o"
    assert debug_payload["selected_provider"] == "openai"
    assert debug_payload["fallback_used"] is False
    assert "selection_reason" in debug_payload
    assert isinstance(debug_payload["candidates"], list) and len(debug_payload["candidates"]) >= 1

    # Without the header, no debug metadata should be attached.
    resp_no_debug = client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "Quiet please"}]},
    )
    assert "X-Setu-Routing-Debug" not in resp_no_debug.headers


def test_v1_chat_completions_applies_organization_routing_rule():
    """Epic 4.2 end-to-end: a rule created via /routing-rules for an org actually
    changes what /v1/chat/completions does when that org's header is sent."""
    org_id = str(uuid.uuid4())
    create_resp = client.post(
        "/routing-rules",
        json={
            "organization_id": org_id,
            "name": "always-use-ollama",
            "condition_expression": "latency > -1ms",
            "action_type": "use",
            "action_provider": "ollama",
        },
    )
    assert create_resp.status_code == 201

    resp = client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        headers={"X-Setu-Organization-Id": org_id, "X-Setu-Debug": "true"},
    )
    assert resp.status_code == 200
    import json

    debug_payload = json.loads(resp.headers["X-Setu-Routing-Debug"])
    assert debug_payload["selected_provider"] == "ollama"
    assert debug_payload["rule_applied"] == "always-use-ollama"

    # A different / no organization header shouldn't be affected by another org's rule.
    resp_other = client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp_other.status_code == 200
    assert resp_other.json()["model"] == "gpt-4o"


def test_v1_chat_completions_streaming_fails_over_before_first_chunk():
    """Epic 4.4 idempotency boundary: a provider that fails before yielding any output
    should be failed over transparently, same as the non-streaming case."""

    async def _broken_stream(_request):
        raise ConnectionError("upstream reset before first byte")
        yield "unreachable"  # pragma: no cover - makes this an async generator

    async def _working_stream(_request):
        yield 'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
        yield "data: [DONE]\n\n"

    with (
        patch("plugins.providers.openai.plugin.OpenAIProviderPlugin.chat", side_effect=lambda req: _broken_stream(req)),
        patch("plugins.providers.gemini.plugin.GeminiProviderPlugin.chat", side_effect=lambda req: _working_stream(req)),
    ):
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}], "stream": True},
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        text = resp.text
        assert '"content":"hi"' in text
        assert "[DONE]" in text
        assert "unreachable" not in text


def test_v1_chat_completions_rule_reject_returns_403():
    org_id = str(uuid.uuid4())
    client.post(
        "/routing-rules",
        json={
            "organization_id": org_id,
            "name": "block-expensive",
            "condition_expression": "estimated_cost > 0.0001",
            "action_type": "reject",
        },
    )

    resp = client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        headers={"X-Setu-Organization-Id": org_id},
    )
    assert resp.status_code == 403
    assert "block-expensive" in resp.json()["detail"]


def test_v1_embeddings_provider_exception():
    with patch("plugins.providers.openai.plugin.OpenAIProviderPlugin.embeddings", side_effect=RuntimeError("Embedding failed")):
        resp = client.post(
            "/v1/embeddings",
            json={
                "model": "text-embedding-3-small",
                "input": "Trigger failure",
            },
        )
        assert resp.status_code == 500
        assert "Embedding request failed" in resp.json()["detail"]
