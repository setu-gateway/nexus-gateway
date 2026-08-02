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
