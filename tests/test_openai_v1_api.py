from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
import pytest

from apps.gateway.main import app

client = TestClient(app)


def test_v1_models_endpoint():
    resp = client.get("/v1/models")
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "list"
    assert len(data["data"]) >= 5
    model_ids = [m["id"] for m in data["data"]]
    assert "gpt-4o" in model_ids
    assert "claude-3-5-sonnet" in model_ids


def test_v1_chat_completions_non_streaming():
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Hello Nexus Gateway"}],
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
    # Missing messages field
    no_msg = client.post("/v1/chat/completions", json={"model": "gpt-4o"})
    assert no_msg.status_code == 400

    # Missing input field in embeddings
    no_input = client.post("/v1/embeddings", json={"model": "text-embedding-3-small"})
    assert no_input.status_code == 400


def test_v1_chat_completions_provider_exception():
    with patch("plugins.providers.openai.plugin.OpenAIProviderPlugin.chat", side_effect=RuntimeError("Provider failed")):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "Trigger failure"}],
            },
        )
        assert resp.status_code == 500
        assert "Provider request failed" in resp.json()["detail"]


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
