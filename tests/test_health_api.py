from fastapi.testclient import TestClient

from apps.gateway.main import app

client = TestClient(app)


def test_liveness_endpoint():
    response = client.get("/live")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "alive"


def test_version_endpoint():
    response = client.get("/version")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "setu-gateway"
    assert data["version"] == "0.1.0"
    assert "python_version" in data
    assert "environment" in data


def test_readiness_endpoint():
    response = client.get("/ready")
    assert response.status_code in (200, 503)
    data = response.json()
    assert "status" in data
    assert "details" in data
    assert "database" in data["details"]
    assert "redis" in data["details"]


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code in (200, 503)
    data = response.json()
    assert data["status"] in ("ok", "degraded", "unhealthy")
    assert data["service"] == "gateway"
    assert "components" in data
