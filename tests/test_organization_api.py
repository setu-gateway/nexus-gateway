from fastapi.testclient import TestClient
import pytest

from apps.gateway.main import app

client = TestClient(app)


def test_organization_crud_lifecycle():
    # 1. Create Organization
    create_resp = client.post(
        "/organizations",
        json={"name": "Acme AI Corp", "plan": "enterprise"},
    )
    assert create_resp.status_code == 201
    org = create_resp.json()
    assert org["name"] == "Acme AI Corp"
    assert org["slug"] == "acme-ai-corp"
    assert org["plan"] == "enterprise"
    org_id = org["id"]

    # 2. List Organizations
    list_resp = client.get("/organizations")
    assert list_resp.status_code == 200
    orgs = list_resp.json()
    assert any(o["id"] == org_id for o in orgs)

    # 3. Get Organization by ID
    get_resp = client.get(f"/organizations/{org_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["name"] == "Acme AI Corp"

    # 4. Patch Organization
    patch_resp = client.patch(
        f"/organizations/{org_id}",
        json={"name": "Acme AI Technologies", "plan": "custom"},
    )
    assert patch_resp.status_code == 200
    updated = patch_resp.json()
    assert updated["name"] == "Acme AI Technologies"
    assert updated["plan"] == "custom"

    # 5. Delete Organization
    del_resp = client.delete(f"/organizations/{org_id}")
    assert del_resp.status_code == 200

    # 6. Verify 404 after deletion
    get_after_del = client.get(f"/organizations/{org_id}")
    assert get_after_del.status_code == 404


def test_duplicate_slug_conflict():
    client.post("/organizations", json={"name": "Unique Tech", "slug": "unique-tech"})
    dup_resp = client.post("/organizations", json={"name": "Unique Tech Duplicate", "slug": "unique-tech"})
    assert dup_resp.status_code == 409
