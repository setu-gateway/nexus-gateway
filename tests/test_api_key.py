from conftest import register_and_login
from fastapi.testclient import TestClient

from apps.gateway.auth.api_key import generate_api_key, mask_api_key, verify_api_key
from apps.gateway.main import app

client = TestClient(app)


def test_api_key_generation_and_hashing():
    plaintext, hashed = generate_api_key(prefix="sk_setu_")

    assert plaintext.startswith("sk_setu_")
    assert hashed != plaintext
    assert len(hashed) == 64  # SHA-256 hex string

    # Verify hashing and constant-time match
    assert verify_api_key(plaintext, hashed) is True
    assert verify_api_key("sk_setu_wrong_key", hashed) is False

    # Masking test
    masked = mask_api_key(plaintext)
    assert masked.startswith("sk_setu_")
    assert "..." in masked


def test_api_key_crud_endpoints():
    org_id, headers = register_and_login(client)
    project = client.post("/projects", json={"name": "Key Test Project", "organization_id": org_id}, headers=headers).json()
    project_id = project["id"]

    # 1. Create API Key
    create_resp = client.post(
        "/keys",
        json={"project_id": project_id, "name": "Production Key"},
        headers=headers,
    )
    assert create_resp.status_code == 201
    data = create_resp.json()

    assert data["name"] == "Production Key"
    assert data["project_id"] == project_id
    assert data["key"].startswith("sk_setu_")
    assert "..." in data["masked_key"]
    key_id = data["id"]

    # 2. List API Keys (must mask keys, never return plaintext)
    list_resp = client.get(f"/keys?project_id={project_id}", headers=headers)
    assert list_resp.status_code == 200
    keys = list_resp.json()
    assert len(keys) >= 1
    found_key = next(k for k in keys if k["id"] == key_id)
    assert "key" not in found_key
    assert "masked_key" in found_key

    # 3. Get Key Metadata
    get_resp = client.get(f"/keys/{key_id}", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["name"] == "Production Key"

    # 4. Revoke Key
    del_resp = client.delete(f"/keys/{key_id}", headers=headers)
    assert del_resp.status_code == 200

    # 5. Verify 404 after deletion
    assert client.get(f"/keys/{key_id}", headers=headers).status_code == 404
