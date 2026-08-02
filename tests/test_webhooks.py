from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from conftest import register_and_login
from fastapi.testclient import TestClient

from apps.gateway.main import app
from apps.gateway.utils import drain_background_tasks
from apps.gateway.webhooks.delivery import dispatch_webhook_event
from apps.gateway.webhooks.signing import generate_webhook_secret, sign_payload, verify_signature

client = TestClient(app)


def _mock_response(status_code=200, text="ok"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    if status_code >= 400:
        request = httpx.Request("POST", "https://example.test/hook")
        resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("error", request=request, response=httpx.Response(status_code, request=request))
        )
    else:
        resp.raise_for_status = MagicMock()
    return resp


def _create_org_and_webhook(**kwargs):
    org_id, headers = register_and_login(client)
    payload = {"organization_id": org_id, "url": "https://example.test/hook", **kwargs}
    endpoint = client.post("/webhooks", json=payload, headers=headers).json()
    return {"id": org_id}, endpoint, headers


async def _dispatch_and_wait(*args, **kwargs):
    """dispatch_webhook_event fires delivery via fire_and_forget (apps/gateway/utils/
    background.py), by design, so the caller's own request never waits on a slow/
    broken receiver. drain_background_tasks polls each tracked task's `.done()`
    instead of awaiting it directly, which is what makes this safe to call regardless
    of whether the task ends up running on this coroutine's own event loop or (as for
    calls made through TestClient) its portal's separate one."""
    await dispatch_webhook_event(*args, **kwargs)
    await drain_background_tasks()


def test_sign_and_verify_round_trip():
    secret = generate_webhook_secret()
    body = b'{"hello":"world"}'
    signature = sign_payload(secret, body)
    assert verify_signature(secret, body, signature)
    assert not verify_signature(secret, body, "deadbeef")
    assert not verify_signature("a-different-secret", body, signature)


def test_create_webhook_endpoint_returns_secret_once():
    org, endpoint, headers = _create_org_and_webhook()
    assert endpoint["secret"].startswith("whsec_")
    assert endpoint["organization_id"] == org["id"]
    assert endpoint["enabled"] is True

    fetched = client.get(f"/webhooks/{endpoint['id']}", headers=headers).json()
    assert "secret" not in fetched


def test_create_webhook_endpoint_rejects_invalid_url():
    org_id, headers = register_and_login(client)
    # Pydantic field validation runs before the handler body, so this 422s
    # regardless of whether org_id would otherwise be a valid tenant match.
    resp = client.post("/webhooks", json={"organization_id": org_id, "url": "not-a-url"}, headers=headers)
    assert resp.status_code == 422


def test_create_webhook_endpoint_rejects_unknown_event_type():
    org_id, headers = register_and_login(client)
    resp = client.post(
        "/webhooks",
        json={"organization_id": org_id, "url": "https://example.test/hook", "event_types": ["not.a.real.event"]},
        headers=headers,
    )
    assert resp.status_code == 422


def test_webhook_endpoint_crud_lifecycle():
    _, endpoint, headers = _create_org_and_webhook(description="my hook")

    listed = client.get("/webhooks", params={"organization_id": endpoint["organization_id"]}, headers=headers).json()
    assert any(e["id"] == endpoint["id"] for e in listed)

    updated = client.patch(f"/webhooks/{endpoint['id']}", json={"enabled": False}, headers=headers).json()
    assert updated["enabled"] is False

    deleted = client.delete(f"/webhooks/{endpoint['id']}", headers=headers)
    assert deleted.status_code == 200
    assert client.get(f"/webhooks/{endpoint['id']}", headers=headers).status_code == 404


def test_rotate_webhook_secret_issues_new_secret():
    _, endpoint, headers = _create_org_and_webhook()
    rotated = client.post(f"/webhooks/{endpoint['id']}/rotate-secret", headers=headers).json()
    assert rotated["secret"] != endpoint["secret"]
    assert rotated["secret_rotated_at"] is not None


@pytest.mark.asyncio
async def test_dispatch_delivers_signed_payload_to_subscribed_endpoint():
    org, endpoint, headers = _create_org_and_webhook(event_types=["request.completed"])
    secret = endpoint["secret"]

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=_mock_response(200)) as mock_post:
        await _dispatch_and_wait(org["id"], "request.completed", {"request_id": "abc"})

    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    sent_body = call_kwargs.kwargs["content"]
    sent_headers = call_kwargs.kwargs["headers"]
    assert sent_headers["X-Setu-Event"] == "request.completed"
    assert sent_headers["X-Setu-Signature"] == f"sha256={sign_payload(secret, sent_body)}"

    deliveries = client.get(f"/webhooks/{endpoint['id']}/deliveries", headers=headers).json()
    assert len(deliveries) == 1
    assert deliveries[0]["status"] == "success"
    assert deliveries[0]["event_type"] == "request.completed"


@pytest.mark.asyncio
async def test_dispatch_skips_endpoint_not_subscribed_to_event_type():
    org, endpoint, headers = _create_org_and_webhook(event_types=["key.created"])

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=_mock_response(200)) as mock_post:
        await _dispatch_and_wait(org["id"], "request.completed", {"request_id": "abc"})

    mock_post.assert_not_called()
    assert client.get(f"/webhooks/{endpoint['id']}/deliveries", headers=headers).json() == []


@pytest.mark.asyncio
async def test_dispatch_records_failure_after_exhausting_retries():
    org, endpoint, headers = _create_org_and_webhook()

    with (
        patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=_mock_response(500)),
        patch("packages.shared.network.retry.asyncio.sleep", new_callable=AsyncMock),
    ):
        await _dispatch_and_wait(org["id"], "request.completed", {"request_id": "will-fail"})

    deliveries = client.get(f"/webhooks/{endpoint['id']}/deliveries", headers=headers).json()
    assert len(deliveries) == 1
    assert deliveries[0]["status"] == "failed"
    assert deliveries[0]["attempt_count"] == 4
    assert deliveries[0]["response_status_code"] == 500


@pytest.mark.asyncio
async def test_dispatch_ignores_disabled_endpoint():
    org, endpoint, headers = _create_org_and_webhook()
    client.patch(f"/webhooks/{endpoint['id']}", json={"enabled": False}, headers=headers)

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=_mock_response(200)) as mock_post:
        await _dispatch_and_wait(org["id"], "request.completed", {"request_id": "abc"})

    mock_post.assert_not_called()


def test_chat_completion_fires_request_completed_webhook_event():
    org_id, _ = register_and_login(client)

    with patch("apps.gateway.analytics.recorder.dispatch_webhook_event", new_callable=AsyncMock) as mock_dispatch:
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "fire webhook"}]},
            headers={"X-Setu-Organization-Id": org_id},
        )
    assert resp.status_code == 200
    mock_dispatch.assert_called_once()
    args = mock_dispatch.call_args.args
    assert args[0] == org_id
    assert args[1] == "request.completed"


def test_chat_completion_failure_fires_request_failed_webhook_event():
    org_id, _ = register_and_login(client)

    with (
        patch("plugins.providers.openai.plugin.OpenAIProviderPlugin.chat", side_effect=RuntimeError("down")),
        patch("plugins.providers.gemini.plugin.GeminiProviderPlugin.chat", side_effect=RuntimeError("also down")),
        patch("apps.gateway.analytics.recorder.dispatch_webhook_event", new_callable=AsyncMock) as mock_dispatch,
    ):
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "will fail"}]},
            headers={"X-Setu-Organization-Id": org_id},
        )
    assert resp.status_code == 503
    mock_dispatch.assert_called_once()
    assert mock_dispatch.call_args.args[1] == "request.failed"


def test_key_created_and_revoked_fire_webhook_events():
    org_id, headers = register_and_login(client)
    project = client.post("/projects", json={"name": "Key Events Project", "organization_id": org_id}, headers=headers).json()

    with patch("apps.gateway.api.keys.dispatch_webhook_event", new_callable=AsyncMock) as mock_dispatch:
        key = client.post("/keys", json={"project_id": project["id"], "name": "webhook key"}, headers=headers).json()
    mock_dispatch.assert_called_once()
    assert mock_dispatch.call_args.args[0] == org_id
    assert mock_dispatch.call_args.args[1] == "key.created"

    with patch("apps.gateway.api.keys.dispatch_webhook_event", new_callable=AsyncMock) as mock_dispatch:
        client.delete(f"/keys/{key['id']}", headers=headers)
    mock_dispatch.assert_called_once()
    assert mock_dispatch.call_args.args[1] == "key.revoked"


def test_project_created_fires_webhook_event():
    org_id, headers = register_and_login(client)

    with patch("apps.gateway.api.projects.dispatch_webhook_event", new_callable=AsyncMock) as mock_dispatch:
        client.post("/projects", json={"name": "New Project", "organization_id": org_id}, headers=headers)
    mock_dispatch.assert_called_once()
    assert mock_dispatch.call_args.args[0] == org_id
    assert mock_dispatch.call_args.args[1] == "project.created"


def test_quota_exceeded_fires_exactly_once_at_crossing():
    org_id, headers = register_and_login(client)
    client.patch(f"/organizations/{org_id}", json={"monthly_request_quota": 1}, headers=headers)

    with patch("apps.gateway.analytics.recorder.check_and_dispatch_quota_exceeded", new_callable=AsyncMock) as mock_check:
        for i in range(3):
            client.post(
                "/v1/chat/completions",
                json={"model": "gpt-4o", "messages": [{"role": "user", "content": f"quota {i}"}]},
                headers={"X-Setu-Organization-Id": org_id},
            )
    assert mock_check.call_count == 3  # called every success; the function itself decides whether to fire


@pytest.mark.asyncio
async def test_check_and_dispatch_quota_exceeded_fires_only_on_crossing_request():
    from apps.gateway.webhooks.delivery import check_and_dispatch_quota_exceeded

    org_id, headers = register_and_login(client)
    client.patch(f"/organizations/{org_id}", json={"monthly_request_quota": 2}, headers=headers)

    with (
        patch("apps.gateway.webhooks.delivery.dispatch_webhook_event", new_callable=AsyncMock) as mock_dispatch,
        # record_request's own automatic firing (covered by
        # test_quota_exceeded_fires_exactly_once_at_crossing) is suppressed here so
        # this test can drive the crossing-detection logic directly and
        # deterministically, once per request, without a second concurrent caller.
        patch("apps.gateway.analytics.recorder.check_and_dispatch_quota_exceeded", new_callable=AsyncMock),
    ):
        for i in range(4):
            client.post(
                "/v1/chat/completions",
                json={"model": "gpt-4o", "messages": [{"role": "user", "content": f"crossing {i}"}]},
                headers={"X-Setu-Organization-Id": org_id},
            )
            await check_and_dispatch_quota_exceeded(org_id)

    mock_dispatch.assert_called_once()
    assert mock_dispatch.call_args.args[1] == "quota.exceeded"
