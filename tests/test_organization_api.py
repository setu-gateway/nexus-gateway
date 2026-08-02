from conftest import register_and_login
from fastapi.testclient import TestClient

from apps.gateway.main import app

client = TestClient(app)


def test_organization_crud_lifecycle():
    # A registered user's own organization is what list/get/patch/delete exercise -
    # POST /organizations (a separate, Role.OWNER-gated path for creating an
    # additional standalone org) is covered on its own below.
    org_id, headers = register_and_login(client)

    # 1. List Organizations - a user sees only their own
    list_resp = client.get("/organizations", headers=headers)
    assert list_resp.status_code == 200
    orgs = list_resp.json()
    assert any(o["id"] == org_id for o in orgs)

    # 2. Get Organization by ID
    get_resp = client.get(f"/organizations/{org_id}", headers=headers)
    assert get_resp.status_code == 200

    # 3. Patch Organization
    patch_resp = client.patch(
        f"/organizations/{org_id}",
        json={"name": "Acme AI Technologies", "plan": "custom"},
        headers=headers,
    )
    assert patch_resp.status_code == 200
    updated = patch_resp.json()
    assert updated["name"] == "Acme AI Technologies"
    assert updated["plan"] == "custom"

    # 4. Delete Organization (requires Role.OWNER - which registering grants). This
    # cascades to the organization's users (Organization.users is
    # cascade="all, delete-orphan") - the registering user WAS that organization's
    # only member, so their own account goes with it.
    del_resp = client.delete(f"/organizations/{org_id}", headers=headers)
    assert del_resp.status_code == 200

    # 5. The deleted user's own token is now invalid, not just the organization gone.
    get_after_del = client.get(f"/organizations/{org_id}", headers=headers)
    assert get_after_del.status_code == 401


def test_create_standalone_organization_requires_owner_role():
    _, headers = register_and_login(client)

    create_resp = client.post("/organizations", json={"name": "Acme AI Corp", "plan": "enterprise"}, headers=headers)
    assert create_resp.status_code == 201, create_resp.text
    org = create_resp.json()
    assert org["name"] == "Acme AI Corp"
    assert org["slug"] == "acme-ai-corp"
    assert org["plan"] == "enterprise"

    unauthenticated_resp = client.post("/organizations", json={"name": "No Auth Co"})
    assert unauthenticated_resp.status_code == 401


def test_duplicate_slug_conflict():
    _, headers = register_and_login(client)
    client.post("/organizations", json={"name": "Unique Tech", "slug": "unique-tech"}, headers=headers)
    dup_resp = client.post("/organizations", json={"name": "Unique Tech Duplicate", "slug": "unique-tech"}, headers=headers)
    assert dup_resp.status_code == 409


def test_organization_quota_fields_round_trip_through_create_and_patch():
    org_id, headers = register_and_login(client)
    patched = client.patch(
        f"/organizations/{org_id}",
        json={"monthly_request_quota": 1000, "monthly_spend_quota_usd": 50.0},
        headers=headers,
    ).json()
    assert patched["monthly_request_quota"] == 1000
    assert patched["monthly_spend_quota_usd"] == 50.0

    updated = client.patch(f"/organizations/{org_id}", json={"monthly_request_quota": 2000}, headers=headers).json()
    assert updated["monthly_request_quota"] == 2000
    assert updated["monthly_spend_quota_usd"] == 50.0


def test_organization_usage_with_no_quota_is_unlimited():
    org_id, headers = register_and_login(client)

    usage = client.get(f"/organizations/{org_id}/usage", headers=headers).json()
    assert usage["requests_used"] == 0
    assert usage["monthly_request_quota"] is None
    assert usage["requests_remaining"] is None
    assert usage["is_over_request_quota"] is False
    assert usage["is_over_spend_quota"] is False


def test_organization_usage_tracks_requests_and_cost():
    org_id, headers = register_and_login(client)
    client.patch(f"/organizations/{org_id}", json={"monthly_request_quota": 5, "monthly_spend_quota_usd": 10.0}, headers=headers)

    for i in range(3):
        # /v1/chat/completions expects an API key (or nothing) in Authorization, not
        # a dashboard session JWT - only the org-scoping header carries over here.
        client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": f"usage {i}"}]},
            headers={"X-Setu-Organization-Id": org_id},
        )

    usage = client.get(f"/organizations/{org_id}/usage", headers=headers).json()
    assert usage["requests_used"] == 3
    assert usage["requests_remaining"] == 2
    assert usage["estimated_cost_used"] > 0
    assert usage["is_over_request_quota"] is False


def test_organization_usage_flags_over_quota_without_blocking_requests():
    org_id, headers = register_and_login(client)
    client.patch(f"/organizations/{org_id}", json={"monthly_request_quota": 1}, headers=headers)

    for i in range(2):
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": f"over quota {i}"}]},
            headers={"X-Setu-Organization-Id": org_id},
        )
        # Tracking only - the gateway never rejects a request for being over quota.
        assert resp.status_code == 200

    usage = client.get(f"/organizations/{org_id}/usage", headers=headers).json()
    assert usage["requests_used"] == 2
    assert usage["is_over_request_quota"] is True
    assert usage["requests_remaining"] == 0


def test_organization_usage_404_for_unknown_org():
    _, headers = register_and_login(client)
    assert client.get("/organizations/not-a-real-id/usage", headers=headers).status_code == 404
