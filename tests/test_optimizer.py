from conftest import register_and_login
from fastapi.testclient import TestClient

from apps.gateway.main import app

client = TestClient(app)


def test_recommends_a_cheaper_model_for_an_expensive_workload():
    org_id, headers = register_and_login(client)

    for i in range(5):
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "claude-3-5-sonnet", "messages": [{"role": "user", "content": f"expensive request {i}"}]},
            headers={"X-Setu-Organization-Id": org_id},
        )
        assert resp.status_code == 200

    recs = client.get("/optimizer/recommendations", params={"organization_id": org_id}, headers=headers).json()

    match = next((r for r in recs if r["current_model"] == "claude-3-5-sonnet"), None)
    assert match is not None, f"expected a recommendation for claude-3-5-sonnet, got: {recs}"
    assert match["recommended_model"] != "claude-3-5-sonnet"
    assert match["estimated_savings_pct"] > 0
    assert match["projected_savings_usd"] > 0
    assert match["based_on_requests"] == 5
    assert match["trade_off"]


def test_no_recommendation_when_already_on_the_cheapest_model():
    org_id, headers = register_and_login(client)
    client.post(
        "/v1/chat/completions",
        json={"model": "llama3", "messages": [{"role": "user", "content": "already free"}]},
        headers={"X-Setu-Organization-Id": org_id},
    )

    recs = client.get("/optimizer/recommendations", params={"organization_id": org_id}, headers=headers).json()
    assert not any(r["current_model"] == "llama3" for r in recs)


def test_no_usage_means_no_recommendations():
    org_id, headers = register_and_login(client)
    recs = client.get("/optimizer/recommendations", params={"organization_id": org_id}, headers=headers).json()
    assert recs == []


def test_cost_recommendations_for_another_organization_is_forbidden():
    _org_id, headers = register_and_login(client)
    other_org_id, _ = register_and_login(client)
    resp = client.get("/optimizer/recommendations", params={"organization_id": other_org_id}, headers=headers)
    assert resp.status_code == 403
