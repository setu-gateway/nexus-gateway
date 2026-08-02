from conftest import register_and_login
from fastapi.testclient import TestClient

from apps.gateway.main import app

client = TestClient(app)


def _create_org_project():
    org_id, headers = register_and_login(client)
    project = client.post("/projects", json={"name": "Scoped Keys Project", "organization_id": org_id}, headers=headers).json()
    return {"id": org_id}, project, headers


def _create_key(project_id: str, headers: dict, **kwargs) -> dict:
    payload = {"project_id": project_id, "name": kwargs.pop("name", "test key"), **kwargs}
    resp = client.post("/keys", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _auth(key: dict) -> dict:
    return {"Authorization": f"Bearer {key['key']}"}


def test_legacy_key_without_permissions_has_full_access():
    _, project, dash_headers = _create_org_project()
    key = _create_key(project["id"], dash_headers)
    assert key["permissions"] is None
    headers = _auth(key)

    assert (
        client.post(
            "/v1/chat/completions", json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]}, headers=headers
        ).status_code
        == 200
    )
    assert client.post("/v1/embeddings", json={"model": "text-embedding-3-small", "input": "hi"}, headers=headers).status_code == 200
    assert client.get("/v1/models", headers=headers).status_code == 200
    assert client.get("/analytics/summary", headers=headers).status_code == 200
    assert client.get("/keys", headers=headers).status_code == 200


def test_key_scoped_to_chat_only_is_blocked_from_other_permissions():
    _, project, dash_headers = _create_org_project()
    key = _create_key(project["id"], dash_headers, permissions=["chat"])
    headers = _auth(key)

    assert (
        client.post(
            "/v1/chat/completions", json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]}, headers=headers
        ).status_code
        == 200
    )

    resp = client.post("/v1/embeddings", json={"model": "text-embedding-3-small", "input": "hi"}, headers=headers)
    assert resp.status_code == 403

    resp = client.get("/v1/models", headers=headers)
    assert resp.status_code == 403

    resp = client.get("/analytics/summary", headers=headers)
    assert resp.status_code == 403

    resp = client.get("/keys", headers=headers)
    assert resp.status_code == 403


def test_admin_permission_gates_key_management():
    _, project, dash_headers = _create_org_project()
    admin_key = _create_key(project["id"], dash_headers, name="admin key", permissions=["admin"])
    limited_key = _create_key(project["id"], dash_headers, name="limited key", permissions=["chat"])

    resp = client.post("/keys", json={"project_id": project["id"], "name": "should fail"}, headers=_auth(limited_key))
    assert resp.status_code == 403

    resp = client.post("/keys", json={"project_id": project["id"], "name": "should succeed"}, headers=_auth(admin_key))
    assert resp.status_code == 201


def test_invalid_permission_value_rejected_at_creation():
    _, project, headers = _create_org_project()
    resp = client.post("/keys", json={"project_id": project["id"], "permissions": ["not_a_real_permission"]}, headers=headers)
    assert resp.status_code == 422


def test_invalid_ip_entry_rejected_at_creation():
    _, project, headers = _create_org_project()
    resp = client.post("/keys", json={"project_id": project["id"], "allowed_ips": ["not-an-ip"]}, headers=headers)
    assert resp.status_code == 422


def test_ip_allowlist_blocks_mismatched_ip():
    _, project, dash_headers = _create_org_project()
    key = _create_key(project["id"], dash_headers, allowed_ips=["203.0.113.99"])

    # Default TestClient presents as host "testclient", which isn't in the allowlist.
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        headers=_auth(key),
    )
    assert resp.status_code == 401


def test_ip_allowlist_allows_matching_ip():
    _, project, dash_headers = _create_org_project()
    key = _create_key(project["id"], dash_headers, allowed_ips=["203.0.113.5/32"])

    spoofed_client = TestClient(app, client=("203.0.113.5", 12345))
    resp = spoofed_client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        headers=_auth(key),
    )
    assert resp.status_code == 200


def test_provider_allowlist_restricts_routing_to_permitted_provider():
    _, project, dash_headers = _create_org_project()
    key = _create_key(project["id"], dash_headers, allowed_providers=["gemini"])

    resp = client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        headers=_auth(key),
    )
    assert resp.status_code == 200
    assert "gemini" in resp.json()["choices"][0]["message"]["content"].lower()


def test_provider_allowlist_rejects_when_no_candidate_matches():
    _, project, dash_headers = _create_org_project()
    key = _create_key(project["id"], dash_headers, allowed_providers=["not-a-real-provider"])

    resp = client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        headers=_auth(key),
    )
    assert resp.status_code == 403


def test_model_allowlist_restricts_routing_to_permitted_model():
    # anthropic is disabled by default (packages/shared/config/providers_config.py), so
    # gemini-1.5-pro - also a flagship+vision equivalent of gpt-4o - is the reliable
    # cross-provider candidate to restrict to here.
    _, project, dash_headers = _create_org_project()
    key = _create_key(project["id"], dash_headers, allowed_models=["gemini-1.5-pro"])

    resp = client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        headers=_auth(key),
    )
    assert resp.status_code == 200
    assert "gemini" in resp.json()["choices"][0]["message"]["content"].lower()


def test_model_allowlist_rejects_when_no_candidate_matches():
    _, project, dash_headers = _create_org_project()
    key = _create_key(project["id"], dash_headers, allowed_models=["not-a-real-model-id"])

    resp = client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        headers=_auth(key),
    )
    assert resp.status_code == 403


def test_rate_limit_field_round_trips_through_key_creation():
    _, project, headers = _create_org_project()
    key = _create_key(project["id"], headers, rate_limit_per_minute=42)
    assert key["rate_limit_per_minute"] == 42

    fetched = client.get(f"/keys/{key['id']}", headers=headers).json()
    assert fetched["rate_limit_per_minute"] == 42


def test_invalid_api_key_still_rejected_outright():
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": "Bearer sk_setu_totally_made_up"},
    )
    assert resp.status_code == 401
