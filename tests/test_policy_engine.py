from conftest import register_and_login, retry_on_lock
from fastapi.testclient import TestClient

from apps.gateway.main import app
from apps.gateway.policy import find_secrets
from apps.gateway.utils import drain_background_tasks

client = TestClient(app)


# --- secret scanner ----------------------------------------------------------------


def test_find_secrets_detects_aws_access_key():
    matches = find_secrets("here is my key AKIAABCDEFGHIJKLMNOP for the deploy")
    assert any(m.label == "aws_access_key_id" for m in matches)


def test_find_secrets_detects_openai_key():
    matches = find_secrets("use sk-abcdefghijklmnopqrstuvwx1234 as the key")
    assert any(m.label == "openai_api_key" for m in matches)


def test_find_secrets_detects_private_key_block():
    matches = find_secrets("-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...")
    assert any(m.label == "private_key_block" for m in matches)


def test_find_secrets_ignores_ordinary_text():
    assert find_secrets("What's the weather like in San Francisco today?") == []


# --- CRUD API ------------------------------------------------------------------------


async def test_policy_crud_lifecycle():
    org_id, headers = register_and_login(client)

    create_resp = client.post(
        "/policies",
        json={
            "organization_id": org_id,
            "name": "No OpenAI",
            "policy_type": "provider_denylist",
            "config": {"providers": ["openai"]},
        },
        headers=headers,
    )
    assert create_resp.status_code == 201
    policy = create_resp.json()
    assert policy["organization_id"] == org_id
    policy_id = policy["id"]

    list_resp = client.get("/policies", params={"organization_id": org_id}, headers=headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    get_resp = client.get(f"/policies/{policy_id}", headers=headers)
    assert get_resp.status_code == 200

    patch_resp = client.patch(f"/policies/{policy_id}", json={"enabled": False}, headers=headers)
    assert patch_resp.status_code == 200
    assert patch_resp.json()["enabled"] is False

    # Each mutating call above fires an audit-log write via fire_and_forget (see
    # apps/gateway/audit) on TestClient's own portal thread/event loop, independent of
    # this request's own DB transaction. Under the full suite's heavier load, the
    # patch's audit write can still be mid-transaction when the delete immediately
    # below opens its own - and SQLite's shared-cache test database (tests/conftest.py)
    # raises "database table is locked" for that overlap rather than queuing it the way
    # Postgres would. Draining here closes most of that race; retry_on_lock is the
    # backstop for what's left (confirmed by testing: draining alone still left an
    # intermittent failure here under repeated full-suite runs).
    await drain_background_tasks()

    delete_resp = await retry_on_lock(lambda: client.delete(f"/policies/{policy_id}", headers=headers))
    assert delete_resp.status_code == 200
    assert client.get(f"/policies/{policy_id}", headers=headers).status_code == 404


def test_create_policy_rejects_unknown_policy_type():
    org_id, headers = register_and_login(client)
    resp = client.post(
        "/policies",
        json={"organization_id": org_id, "name": "bad", "policy_type": "not_a_real_type", "config": {}},
        headers=headers,
    )
    assert resp.status_code == 422


def test_create_policy_rejects_allowlist_missing_providers():
    org_id, headers = register_and_login(client)
    resp = client.post(
        "/policies",
        json={"organization_id": org_id, "name": "bad", "policy_type": "provider_allowlist", "config": {}},
        headers=headers,
    )
    assert resp.status_code == 400


def test_create_policy_rejects_context_window_missing_value():
    org_id, headers = register_and_login(client)
    resp = client.post(
        "/policies",
        json={"organization_id": org_id, "name": "bad", "policy_type": "min_context_window", "config": {}},
        headers=headers,
    )
    assert resp.status_code == 400


def test_list_policies_for_another_organization_is_forbidden():
    _org_id, headers = register_and_login(client)
    other_org_id, _ = register_and_login(client)
    resp = client.get("/policies", params={"organization_id": other_org_id}, headers=headers)
    assert resp.status_code == 403


# --- enforcement on /v1/chat/completions ----------------------------------------------


def test_provider_denylist_blocks_matching_provider():
    org_id, headers = register_and_login(client)
    client.post(
        "/policies",
        json={"organization_id": org_id, "name": "No OpenAI", "policy_type": "provider_denylist", "config": {"providers": ["openai"]}},
        headers=headers,
    )

    resp = client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        headers={"X-Setu-Organization-Id": org_id},
    )
    assert resp.status_code == 403
    assert "No OpenAI" in resp.json()["detail"]


def test_provider_denylist_allows_non_matching_provider():
    org_id, headers = register_and_login(client)
    client.post(
        "/policies",
        json={"organization_id": org_id, "name": "No OpenAI", "policy_type": "provider_denylist", "config": {"providers": ["openai"]}},
        headers=headers,
    )

    resp = client.post(
        "/v1/chat/completions",
        json={"model": "claude-3-5-sonnet", "messages": [{"role": "user", "content": "hi"}]},
        headers={"X-Setu-Organization-Id": org_id},
    )
    assert resp.status_code == 200


def test_min_context_window_blocks_smaller_model():
    org_id, headers = register_and_login(client)
    client.post(
        "/policies",
        json={
            "organization_id": org_id,
            "name": "Need big context",
            "policy_type": "min_context_window",
            "config": {"min_context_window": 128000},
        },
        headers=headers,
    )

    # text-embedding-3-small has an 8191-token context window - well under the floor.
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "text-embedding-3-small", "messages": [{"role": "user", "content": "hi"}]},
        headers={"X-Setu-Organization-Id": org_id},
    )
    assert resp.status_code == 403
    assert "Need big context" in resp.json()["detail"]


def test_block_secrets_policy_blocks_prompt_with_aws_key():
    org_id, headers = register_and_login(client)
    client.post(
        "/policies",
        json={"organization_id": org_id, "name": "No secrets", "policy_type": "block_secrets", "config": {}},
        headers=headers,
    )

    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "debug this: AKIAABCDEFGHIJKLMNOP"}],
        },
        headers={"X-Setu-Organization-Id": org_id},
    )
    assert resp.status_code == 403
    assert "No secrets" in resp.json()["detail"]


def test_block_secrets_policy_allows_clean_prompt():
    org_id, headers = register_and_login(client)
    client.post(
        "/policies",
        json={"organization_id": org_id, "name": "No secrets", "policy_type": "block_secrets", "config": {}},
        headers=headers,
    )

    resp = client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "what's the capital of France?"}]},
        headers={"X-Setu-Organization-Id": org_id},
    )
    assert resp.status_code == 200


def test_disabled_policy_does_not_block():
    org_id, headers = register_and_login(client)
    create_resp = client.post(
        "/policies",
        json={"organization_id": org_id, "name": "No OpenAI", "policy_type": "provider_denylist", "config": {"providers": ["openai"]}},
        headers=headers,
    )
    policy_id = create_resp.json()["id"]
    client.patch(f"/policies/{policy_id}", json={"enabled": False}, headers=headers)

    resp = client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        headers={"X-Setu-Organization-Id": org_id},
    )
    assert resp.status_code == 200


def test_anonymous_request_has_no_policies_to_enforce():
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "AKIAABCDEFGHIJKLMNOP"}]},
    )
    assert resp.status_code == 200
