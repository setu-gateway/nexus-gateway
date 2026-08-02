import pytest
from conftest import register_and_login
from fastapi.testclient import TestClient

from apps.gateway.auth.context import resolve_api_key
from apps.gateway.main import app

client = TestClient(app)


def _create_org_project_and_key():
    org_id, headers = register_and_login(client)
    project = client.post("/projects", json={"name": "Test Project", "organization_id": org_id}, headers=headers).json()
    key = client.post("/keys", json={"project_id": project["id"], "name": "Test Key"}, headers=headers).json()
    return {"id": org_id}, project, key, headers


@pytest.mark.asyncio
async def test_resolve_api_key_returns_none_when_no_header(db_session):
    assert await resolve_api_key(db_session, None) is None
    assert await resolve_api_key(db_session, "") is None
    assert await resolve_api_key(db_session, "NotBearer abc") is None


def test_chat_completion_with_valid_api_key_resolves_organization():
    org, project, key, headers = _create_org_project_and_key()

    client.post(
        "/routing-rules",
        json={
            "organization_id": org["id"],
            "name": "force-groq-for-this-org",
            "condition_expression": "latency > -1ms",
            "action_type": "use",
            "action_provider": "groq",
        },
        headers=headers,
    )

    resp = client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": f"Bearer {key['key']}", "X-Setu-Debug": "true"},
    )
    assert resp.status_code == 200
    import json

    debug = json.loads(resp.headers["X-Setu-Routing-Debug"])
    assert debug["selected_provider"] == "groq"
    assert debug["rule_applied"] == "force-groq-for-this-org"


def test_chat_completion_with_invalid_api_key_returns_401():
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": "Bearer sk_setu_totally_made_up"},
    )
    assert resp.status_code == 401


def test_chat_completion_with_revoked_key_returns_401():
    _, _, key, headers = _create_org_project_and_key()
    client.delete(f"/keys/{key['id']}", headers=headers)

    resp = client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": f"Bearer {key['key']}"},
    )
    assert resp.status_code == 401


def test_chat_completion_api_key_takes_precedence_over_org_header():
    org_a, _, key_a, headers_a = _create_org_project_and_key()
    org_b_id, headers_b = register_and_login(client)

    client.post(
        "/routing-rules",
        json={
            "organization_id": org_a["id"],
            "name": "org-a-rule",
            "condition_expression": "latency > -1ms",
            "action_type": "use",
            "action_provider": "ollama",
        },
        headers=headers_a,
    )
    client.post(
        "/routing-rules",
        json={
            "organization_id": org_b_id,
            "name": "org-b-rule",
            "condition_expression": "latency > -1ms",
            "action_type": "use",
            "action_provider": "groq",
        },
        headers=headers_b,
    )

    # Both an API key (org_a) and an org header (org_b) are present - the key wins.
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        headers={
            "Authorization": f"Bearer {key_a['key']}",
            "X-Setu-Organization-Id": org_b_id,
            "X-Setu-Debug": "true",
        },
    )
    assert resp.status_code == 200
    import json

    debug = json.loads(resp.headers["X-Setu-Routing-Debug"])
    assert debug["rule_applied"] == "org-a-rule"


def test_chat_completion_without_any_auth_still_works():
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 200


def test_api_key_last_used_at_updates_on_successful_auth():
    _, _, key, headers = _create_org_project_and_key()
    before = client.get(f"/keys/{key['id']}", headers=headers).json()
    assert before["last_used_at"] is None

    client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": f"Bearer {key['key']}"},
    )

    after = client.get(f"/keys/{key['id']}", headers=headers).json()
    assert after["last_used_at"] is not None
