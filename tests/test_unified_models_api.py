from fastapi.testclient import TestClient
import pytest

from apps.gateway.main import app

client = TestClient(app)


def test_list_unified_models_endpoint():
    resp = client.get("/models")
    assert resp.status_code == 200
    models = resp.json()
    assert len(models) >= 5

    providers = {m["provider"] for m in models}
    assert "openai" in providers
    assert "ollama" in providers
    assert "anthropic" in providers

    gpt4 = next(m for m in models if m["id"] == "gpt-4o")
    assert gpt4["provider"] == "openai"
    assert gpt4["context_window"] == 128000
    assert gpt4["capabilities"]["tools"] is True


def test_get_single_unified_model():
    resp = client.get("/models/claude-3-5-sonnet")
    assert resp.status_code == 200
    model = resp.json()
    assert model["id"] == "claude-3-5-sonnet"
    assert model["provider"] == "anthropic"
    assert model["context_window"] == 200000

    # 404 test
    bad_resp = client.get("/models/nonexistent_model_123")
    assert bad_resp.status_code == 404
