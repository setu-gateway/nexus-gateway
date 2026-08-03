from fastapi.testclient import TestClient

from apps.gateway.main import app

client = TestClient(app)


def test_serve_playground_ui_endpoint():
    resp = client.get("/playground")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Setu Gateway — Provider Playground" in resp.text
    assert 'button class="btn-submit"' in resp.text


def test_playground_completion_endpoint_success():
    payload = {
        "provider": "openai",
        "model": "gpt-4o",
        "prompt": "Hello Playground",
        "temperature": 0.5,
    }

    resp = client.post("/playground/completion", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["provider"] == "openai"
    assert data["model"] == "gpt-4o"
    assert "raw_response" in data
    assert "latency_ms" in data
    assert data["latency_ms"] >= 0.0
    assert "usage" in data


def test_playground_completion_unsupported_provider():
    payload = {
        "provider": "invalid_provider_name",
        "model": "gpt-4o",
        "prompt": "Test",
    }

    resp = client.post("/playground/completion", json=payload)
    assert resp.status_code == 530 or resp.status_code == 503 or resp.status_code == 500


def test_playground_completion_is_rate_limited_per_ip():
    from apps.gateway.api.playground_api import PLAYGROUND_RATE_LIMIT_PER_MINUTE

    payload = {"provider": "openai", "model": "gpt-4o", "prompt": "spam"}

    for _ in range(PLAYGROUND_RATE_LIMIT_PER_MINUTE):
        resp = client.post("/playground/completion", json=payload)
        assert resp.status_code == 200

    limited = client.post("/playground/completion", json=payload)
    assert limited.status_code == 429
    assert "rate limit" in limited.json()["detail"].lower()
