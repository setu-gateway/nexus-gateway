from fastapi.testclient import TestClient
import pytest

from apps.gateway.main import app

client = TestClient(app)


def test_list_providers_endpoint():
    resp = client.get("/providers")
    assert resp.status_code == 200
    providers = resp.json()
    assert len(providers) >= 4
    names = [p["provider_name"] for p in providers]
    assert "openai" in names
    assert "ollama" in names
    assert "groq" in names


def test_get_single_provider_details():
    resp = client.get("/providers/openai")
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider_name"] == "openai"
    assert data["capabilities"]["chat"] is True
    assert "gpt-4o" in data["models"]

    # Test 404 for non-existent provider
    bad_resp = client.get("/providers/nonexistent_provider_xyz")
    assert bad_resp.status_code == 404


def test_get_provider_health():
    resp = client.get("/providers/openai/health")
    assert resp.status_code == 200
    health = resp.json()
    assert health["status"] in ("ok", "degraded", "offline")


def test_reload_providers_endpoint():
    resp = client.post("/providers/reload")
    assert resp.status_code == 200
    data = resp.json()
    assert "reloaded successfully" in data["message"]
    assert "active_providers_count" in data
