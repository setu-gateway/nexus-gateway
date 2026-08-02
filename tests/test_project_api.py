from conftest import register_and_login
from fastapi.testclient import TestClient

from apps.gateway.main import app

client = TestClient(app)


def test_projects_crud_lifecycle():
    org_id, headers = register_and_login(client)

    # 1. Create Project
    create_resp = client.post(
        "/projects",
        json={
            "name": "Production AI Agent",
            "organization_id": org_id,
            "description": "LLM agent serving production users",
        },
        headers=headers,
    )
    assert create_resp.status_code == 201
    project = create_resp.json()
    assert project["name"] == "Production AI Agent"
    assert project["organization_id"] == org_id
    assert project["description"] == "LLM agent serving production users"
    project_id = project["id"]

    # 2. List Projects
    list_resp = client.get("/projects", headers=headers)
    assert list_resp.status_code == 200
    projects = list_resp.json()
    assert any(p["id"] == project_id for p in projects)

    # 3. Filter Projects by organization_id
    filter_resp = client.get(f"/projects?organization_id={org_id}", headers=headers)
    assert filter_resp.status_code == 200
    filtered = filter_resp.json()
    assert len(filtered) >= 1
    assert all(p["organization_id"] == org_id for p in filtered)

    # 4. Get Project by ID
    get_resp = client.get(f"/projects/{project_id}", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["name"] == "Production AI Agent"

    # 5. Patch Project
    patch_resp = client.patch(
        f"/projects/{project_id}",
        json={"name": "Production AI Agent v2", "description": "Updated description"},
        headers=headers,
    )
    assert patch_resp.status_code == 200
    updated = patch_resp.json()
    assert updated["name"] == "Production AI Agent v2"
    assert updated["description"] == "Updated description"

    # 6. Delete Project
    del_resp = client.delete(f"/projects/{project_id}", headers=headers)
    assert del_resp.status_code == 200

    # 7. Verify 404 after deletion
    get_after_del = client.get(f"/projects/{project_id}", headers=headers)
    assert get_after_del.status_code == 404
