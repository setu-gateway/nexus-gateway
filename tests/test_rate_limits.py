from unittest.mock import patch

import pytest
from conftest import register_and_login
from fastapi.testclient import TestClient

from apps.gateway.main import app
from apps.gateway.ratelimit.limiter import RateLimiter

client = TestClient(app)


@pytest.mark.asyncio
async def test_fixed_window_allows_up_to_limit_then_blocks():
    limiter = RateLimiter()
    for _ in range(3):
        result = await limiter.check("test", "fixed-key", limit=3, window_seconds=60, algorithm="fixed_window")
        assert result.allowed
    blocked = await limiter.check("test", "fixed-key", limit=3, window_seconds=60, algorithm="fixed_window")
    assert not blocked.allowed
    assert blocked.retry_after_seconds > 0


@pytest.mark.asyncio
async def test_sliding_window_allows_up_to_limit_then_blocks():
    limiter = RateLimiter()
    for _ in range(3):
        result = await limiter.check("test", "sliding-key", limit=3, window_seconds=60, algorithm="sliding_window")
        assert result.allowed
    blocked = await limiter.check("test", "sliding-key", limit=3, window_seconds=60, algorithm="sliding_window")
    assert not blocked.allowed


@pytest.mark.asyncio
async def test_token_bucket_allows_up_to_capacity_then_blocks():
    limiter = RateLimiter()
    for _ in range(5):
        result = await limiter.check("test", "bucket-key", limit=5, window_seconds=60, algorithm="token_bucket")
        assert result.allowed
    blocked = await limiter.check("test", "bucket-key", limit=5, window_seconds=60, algorithm="token_bucket")
    assert not blocked.allowed


@pytest.mark.asyncio
async def test_different_scope_values_have_independent_budgets():
    limiter = RateLimiter()
    for _ in range(3):
        assert (await limiter.check("test", "key-a", limit=3, window_seconds=60)).allowed
    # key-b's budget is untouched by key-a's usage.
    assert (await limiter.check("test", "key-b", limit=3, window_seconds=60)).allowed


@pytest.mark.asyncio
async def test_rate_limiter_fails_open_when_redis_unavailable():
    limiter = RateLimiter()
    with patch("apps.gateway.ratelimit.limiter.get_redis_client", side_effect=ConnectionError("redis down")):
        result = await limiter.check("test", "any-key", limit=1, window_seconds=60)
    assert result.allowed is True


def test_create_rate_limit_rule_requires_scope_value_unless_global():
    _, headers = register_and_login(client)
    resp = client.post("/rate-limits", json={"scope_type": "project", "limit": 10}, headers=headers)
    assert resp.status_code == 400

    resp = client.post("/rate-limits", json={"scope_type": "global", "limit": 10}, headers=headers)
    assert resp.status_code == 201


def test_create_rate_limit_rule_rejects_invalid_scope_type():
    _, headers = register_and_login(client)
    resp = client.post("/rate-limits", json={"scope_type": "not-a-scope", "scope_value": "x", "limit": 10}, headers=headers)
    assert resp.status_code == 422


def test_create_rate_limit_rule_rejects_invalid_algorithm():
    _, headers = register_and_login(client)
    resp = client.post("/rate-limits", json={"scope_type": "global", "algorithm": "not-an-algorithm", "limit": 10}, headers=headers)
    assert resp.status_code == 422


def test_rate_limit_rule_crud_lifecycle():
    _, headers = register_and_login(client)
    created = client.post(
        "/rate-limits", json={"scope_type": "endpoint", "scope_value": "/v1/embeddings", "limit": 5, "window_seconds": 30}, headers=headers
    ).json()
    assert created["enabled"] is True

    fetched = client.get(f"/rate-limits/{created['id']}", headers=headers).json()
    assert fetched["limit"] == 5

    updated = client.patch(f"/rate-limits/{created['id']}", json={"limit": 20, "enabled": False}, headers=headers).json()
    assert updated["limit"] == 20
    assert updated["enabled"] is False

    listed = client.get("/rate-limits", params={"scope_type": "endpoint"}, headers=headers).json()
    assert any(r["id"] == created["id"] for r in listed)

    deleted = client.delete(f"/rate-limits/{created['id']}", headers=headers)
    assert deleted.status_code == 200
    assert client.get(f"/rate-limits/{created['id']}", headers=headers).status_code == 404


def test_global_rate_limit_rule_blocks_after_limit_and_reports_retry_after():
    _, headers = register_and_login(client)
    rule = client.post(
        "/rate-limits", json={"scope_type": "global", "algorithm": "fixed_window", "limit": 1, "window_seconds": 60}, headers=headers
    ).json()
    try:
        payload = {"model": "gpt-4o", "messages": [{"role": "user", "content": "first"}]}
        first = client.post("/v1/chat/completions", json=payload)
        assert first.status_code == 200

        second = client.post("/v1/chat/completions", json=payload)
        assert second.status_code == 429
        assert "Retry-After" in second.headers
    finally:
        client.delete(f"/rate-limits/{rule['id']}", headers=headers)


def test_disabled_rate_limit_rule_does_not_block():
    _, headers = register_and_login(client)
    rule = client.post(
        "/rate-limits",
        json={"scope_type": "global", "algorithm": "fixed_window", "limit": 1, "window_seconds": 60, "enabled": False},
        headers=headers,
    ).json()
    try:
        payload = {"model": "gpt-4o", "messages": [{"role": "user", "content": "disabled rule test"}]}
        assert client.post("/v1/chat/completions", json=payload).status_code == 200
        assert client.post("/v1/chat/completions", json=payload).status_code == 200
    finally:
        client.delete(f"/rate-limits/{rule['id']}", headers=headers)


def test_provider_scoped_rate_limit_only_affects_that_provider():
    _, headers = register_and_login(client)
    rule = client.post(
        "/rate-limits",
        json={"scope_type": "provider", "scope_value": "openai", "algorithm": "fixed_window", "limit": 1, "window_seconds": 60},
        headers=headers,
    ).json()
    try:
        openai_payload = {"model": "gpt-4o", "messages": [{"role": "user", "content": "hit openai limit"}]}
        assert client.post("/v1/chat/completions", json=openai_payload).status_code == 200
        assert client.post("/v1/chat/completions", json=openai_payload).status_code == 429

        # A request forced to ollama (unaffected by the openai-scoped rule) still succeeds.
        ollama_payload = {"model": "llama3", "messages": [{"role": "user", "content": "different provider"}]}
        assert client.post("/v1/chat/completions", json=ollama_payload).status_code == 200
    finally:
        client.delete(f"/rate-limits/{rule['id']}", headers=headers)


def test_per_api_key_rate_limit_from_scoped_key_blocks_only_that_key():
    org_id, headers = register_and_login(client)
    project = client.post("/projects", json={"name": "Rate Limit Project", "organization_id": org_id}, headers=headers).json()
    limited_key = client.post(
        "/keys", json={"project_id": project["id"], "name": "limited", "rate_limit_per_minute": 1}, headers=headers
    ).json()
    other_key = client.post("/keys", json={"project_id": project["id"], "name": "other"}, headers=headers).json()

    payload = {"model": "gpt-4o", "messages": [{"role": "user", "content": "per key limit"}]}
    limited_headers = {"Authorization": f"Bearer {limited_key['key']}"}
    other_headers = {"Authorization": f"Bearer {other_key['key']}"}

    assert client.post("/v1/chat/completions", json=payload, headers=limited_headers).status_code == 200
    blocked = client.post("/v1/chat/completions", json=payload, headers=limited_headers)
    assert blocked.status_code == 429

    # A different key on the same project is unaffected.
    assert client.post("/v1/chat/completions", json=payload, headers=other_headers).status_code == 200
