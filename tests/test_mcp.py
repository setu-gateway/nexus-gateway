import json
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from conftest import register_and_login
from fastapi.testclient import TestClient

from apps.gateway.main import app
from apps.gateway.mcp import MCPError, call_tool, check_health, list_tools

client = TestClient(app)


def _request_with_lock_retry(fn, *, attempts=5, initial_delay=0.05):
    """See tests/test_evaluation.py's copy of this helper: a fresh client.<verb>(...)
    call is a fully independent attempt through a new request-scoped session, so
    retrying the whole call safely absorbs a fire-and-forget audit write from an
    earlier request still settling on another connection."""
    delay = initial_delay
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as e:
            if "locked" not in str(e).lower() or attempt == attempts - 1:
                raise
            time.sleep(delay)
            delay *= 2


def _mock_response(status_code=200, json_body=None, content_type="application/json", text=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {"content-type": content_type}
    resp.text = text if text is not None else json.dumps(json_body if json_body is not None else {})
    return resp


def _jsonrpc_result(result, request_id=1):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _jsonrpc_error(code, message, request_id=1):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


# ---------------------------------------------------------------------------
# MCP client (mocked transport, no real network)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_health_returns_server_info():
    server_info = {"protocolVersion": "2025-03-26", "serverInfo": {"name": "demo", "version": "1.0"}}
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=_mock_response(json_body=_jsonrpc_result(server_info))):
        result = await check_health("https://example.test/mcp")
    assert result == server_info


@pytest.mark.asyncio
async def test_check_health_raises_on_jsonrpc_error():
    with (
        patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=_mock_response(json_body=_jsonrpc_error(-32000, "boom"))),
        pytest.raises(MCPError, match="boom"),
    ):
        await check_health("https://example.test/mcp")


@pytest.mark.asyncio
async def test_list_tools_parses_tools_array():
    init_resp = _mock_response(json_body=_jsonrpc_result({"serverInfo": {"name": "demo"}}))
    tools_resp = _mock_response(
        json_body=_jsonrpc_result({"tools": [{"name": "get_weather", "description": "Weather lookup", "inputSchema": {"type": "object"}}]})
    )
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=[init_resp, tools_resp]):
        tools = await list_tools("https://example.test/mcp")
    assert tools == [{"name": "get_weather", "description": "Weather lookup", "inputSchema": {"type": "object"}}]


@pytest.mark.asyncio
async def test_list_tools_raises_when_result_missing_tools_array():
    init_resp = _mock_response(json_body=_jsonrpc_result({}))
    bad_resp = _mock_response(json_body=_jsonrpc_result({"not_tools": []}))
    with (
        patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=[init_resp, bad_resp]),
        pytest.raises(MCPError, match="tools"),
    ):
        await list_tools("https://example.test/mcp")


@pytest.mark.asyncio
async def test_call_tool_returns_content_and_is_error():
    init_resp = _mock_response(json_body=_jsonrpc_result({}))
    call_resp = _mock_response(json_body=_jsonrpc_result({"content": [{"type": "text", "text": "72F"}], "isError": False}))
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=[init_resp, call_resp]):
        result = await call_tool("https://example.test/mcp", "get_weather", {"city": "Paris"})
    assert result["content"][0]["text"] == "72F"
    assert result["isError"] is False


@pytest.mark.asyncio
async def test_call_method_raises_on_non_2xx_http_status():
    with (
        patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=_mock_response(status_code=500, text="server exploded")),
        pytest.raises(MCPError, match="500"),
    ):
        await check_health("https://example.test/mcp")


@pytest.mark.asyncio
async def test_call_method_raises_on_transport_failure():
    with (
        patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=httpx.ConnectError("connection refused")),
        pytest.raises(MCPError, match="Could not reach"),
    ):
        await check_health("https://example.test/mcp")


@pytest.mark.asyncio
async def test_call_method_raises_on_non_json_body():
    with (
        patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=_mock_response(text="<html>not json</html>")),
        pytest.raises(MCPError, match="not valid JSON"),
    ):
        await check_health("https://example.test/mcp")


@pytest.mark.asyncio
async def test_call_method_parses_sse_formatted_response():
    sse_body = f"event: message\ndata: {json.dumps(_jsonrpc_result({'ok': True}))}\n\n"
    resp = _mock_response(content_type="text/event-stream", text=sse_body)
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=resp):
        result = await check_health("https://example.test/mcp")
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_call_method_sends_custom_headers():
    seen_headers = {}

    async def _capture(self, url, json=None, headers=None):
        seen_headers.update(headers or {})
        return _mock_response(json_body=_jsonrpc_result({}))

    with patch("httpx.AsyncClient.post", new=_capture):
        await check_health("https://example.test/mcp", headers={"Authorization": "Bearer secret-token"})
    assert seen_headers["Authorization"] == "Bearer secret-token"


# ---------------------------------------------------------------------------
# API: server CRUD
# ---------------------------------------------------------------------------


def _create_org():
    org_id, auth_headers = register_and_login(client)
    return {"id": org_id}, auth_headers


def _create_server(org=None, auth_headers=None, **overrides):
    """overrides may include the MCPServerCreate payload's own `headers` field
    (extra headers sent to the *external* MCP server) - unrelated to auth_headers,
    which authenticates *this* request against the dashboard-management endpoint."""
    if org is None:
        org, auth_headers = _create_org()
    payload = {"organization_id": org["id"], "name": "Weather Server", "url": "https://mcp.example.test/mcp", **overrides}
    resp = client.post("/mcp/servers", json=payload, headers=auth_headers)
    assert resp.status_code == 201, resp.text
    return org, auth_headers, resp.json()


def test_create_mcp_server_never_echoes_headers():
    _, _, server = _create_server(headers={"Authorization": "Bearer secret"})
    assert "headers" not in server
    assert "secret" not in json.dumps(server)


def test_create_mcp_server_rejects_non_http_url():
    org, auth_headers = _create_org()
    resp = client.post(
        "/mcp/servers", json={"organization_id": org["id"], "name": "Bad", "url": "ftp://example.test"}, headers=auth_headers
    )
    assert resp.status_code == 422


def test_get_mcp_server():
    _, auth_headers, server = _create_server()
    fetched = client.get(f"/mcp/servers/{server['id']}", headers=auth_headers).json()
    assert fetched["id"] == server["id"]
    assert "headers" not in fetched


def test_get_mcp_server_404_for_unknown_id():
    _, auth_headers = _create_org()
    assert client.get(f"/mcp/servers/{uuid.uuid4()}", headers=auth_headers).status_code == 404


def test_list_mcp_servers_scoped_to_organization():
    org_a, headers_a = _create_org()
    org_b, headers_b = _create_org()
    client.post("/mcp/servers", json={"organization_id": org_a["id"], "name": "A", "url": "https://a.test/mcp"}, headers=headers_a)
    client.post("/mcp/servers", json={"organization_id": org_b["id"], "name": "B", "url": "https://b.test/mcp"}, headers=headers_b)
    listed = client.get("/mcp/servers", params={"organization_id": org_a["id"]}, headers=headers_a).json()
    assert len(listed) == 1
    assert listed[0]["name"] == "A"


def test_update_mcp_server():
    _, auth_headers, server = _create_server()
    resp = client.patch(f"/mcp/servers/{server['id']}", json={"enabled": False, "description": "paused"}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert body["description"] == "paused"


def test_delete_mcp_server():
    _, auth_headers, server = _create_server()
    # create_mcp_server fires an audit write via fire_and_forget - see
    # test_evaluation.py's test_delete_eval_suite for why this is retried.
    resp = _request_with_lock_retry(lambda: client.delete(f"/mcp/servers/{server['id']}", headers=auth_headers))
    assert resp.status_code == 200
    assert client.get(f"/mcp/servers/{server['id']}", headers=auth_headers).status_code == 404


# ---------------------------------------------------------------------------
# API: health / tools / call
# ---------------------------------------------------------------------------


def test_health_check_records_success():
    _, auth_headers, server = _create_server()
    with patch(
        "httpx.AsyncClient.post",
        new_callable=AsyncMock,
        return_value=_mock_response(json_body=_jsonrpc_result({"serverInfo": {"name": "demo"}})),
    ):
        resp = client.post(f"/mcp/servers/{server['id']}/health", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["last_health_status"] == "ok"
    assert body["last_health_error"] is None
    assert body["last_health_checked_at"] is not None


def test_health_check_records_failure():
    _, auth_headers, server = _create_server()
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=httpx.ConnectError("refused")):
        resp = client.post(f"/mcp/servers/{server['id']}/health", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["last_health_status"] == "error"
    assert "refused" in body["last_health_error"]


def test_health_check_400_when_server_disabled():
    _, auth_headers, server = _create_server(enabled=False)
    resp = client.post(f"/mcp/servers/{server['id']}/health", headers=auth_headers)
    assert resp.status_code == 400


def test_get_tools_returns_tool_list():
    _, auth_headers, server = _create_server()
    init_resp = _mock_response(json_body=_jsonrpc_result({}))
    tools_resp = _mock_response(json_body=_jsonrpc_result({"tools": [{"name": "get_weather", "description": "lookup"}]}))
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=[init_resp, tools_resp]):
        resp = client.get(f"/mcp/servers/{server['id']}/tools", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["tools"][0]["name"] == "get_weather"


def test_get_tools_502_when_server_unreachable():
    _, auth_headers, server = _create_server()
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=httpx.ConnectError("refused")):
        resp = client.get(f"/mcp/servers/{server['id']}/tools", headers=auth_headers)
    assert resp.status_code == 502


def test_call_tool_success():
    _, _, server = _create_server()
    init_resp = _mock_response(json_body=_jsonrpc_result({}))
    call_resp = _mock_response(json_body=_jsonrpc_result({"content": [{"type": "text", "text": "72F"}], "isError": False}))
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=[init_resp, call_resp]):
        resp = client.post(f"/mcp/servers/{server['id']}/tools/get_weather/call", json={"arguments": {"city": "Paris"}})
    assert resp.status_code == 200
    body = resp.json()
    assert body["content"][0]["text"] == "72F"
    # Serialized by alias (FastAPI's response_model default), matching the MCP
    # spec's own camelCase field name.
    assert body["isError"] is False


def test_call_tool_502_on_mcp_failure():
    _, _, server = _create_server()
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=httpx.ConnectError("refused")):
        resp = client.post(f"/mcp/servers/{server['id']}/tools/get_weather/call", json={"arguments": {}})
    assert resp.status_code == 502


def test_call_tool_400_when_server_disabled():
    _, _, server = _create_server(enabled=False)
    resp = client.post(f"/mcp/servers/{server['id']}/tools/get_weather/call", json={"arguments": {}})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# API: permission gating on tool invocation
# ---------------------------------------------------------------------------


def _create_org_project():
    org_id, auth_headers = register_and_login(client)
    project = client.post("/projects", json={"name": "MCP Perm Project", "organization_id": org_id}, headers=auth_headers).json()
    return {"id": org_id}, project, auth_headers


def _create_key(project_id: str, auth_headers: dict, **kwargs) -> dict:
    payload = {"project_id": project_id, "name": kwargs.pop("name", "test key"), **kwargs}
    resp = client.post("/keys", json=payload, headers=auth_headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _auth(key: dict) -> dict:
    return {"Authorization": f"Bearer {key['key']}"}


def test_call_tool_without_auth_is_allowed():
    _, _, server = _create_server()
    init_resp = _mock_response(json_body=_jsonrpc_result({}))
    call_resp = _mock_response(json_body=_jsonrpc_result({"content": [], "isError": False}))
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=[init_resp, call_resp]):
        resp = client.post(f"/mcp/servers/{server['id']}/tools/get_weather/call", json={})
    assert resp.status_code == 200


def test_call_tool_rejects_key_without_mcp_invoke_permission():
    org, project, auth_headers = _create_org_project()
    _, _, server = _create_server(org=org, auth_headers=auth_headers)
    key = _create_key(project["id"], auth_headers, permissions=["chat"])

    resp = client.post(f"/mcp/servers/{server['id']}/tools/get_weather/call", json={}, headers=_auth(key))
    assert resp.status_code == 403


def test_call_tool_allows_key_with_mcp_invoke_permission():
    org, project, auth_headers = _create_org_project()
    _, _, server = _create_server(org=org, auth_headers=auth_headers)
    key = _create_key(project["id"], auth_headers, permissions=["mcp_invoke"])

    init_resp = _mock_response(json_body=_jsonrpc_result({}))
    call_resp = _mock_response(json_body=_jsonrpc_result({"content": [], "isError": False}))
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=[init_resp, call_resp]):
        resp = client.post(f"/mcp/servers/{server['id']}/tools/get_weather/call", json={}, headers=_auth(key))
    assert resp.status_code == 200


def test_call_tool_rejects_invalid_bearer_token():
    _, _, server = _create_server()
    resp = client.post(
        f"/mcp/servers/{server['id']}/tools/get_weather/call",
        json={},
        headers={"Authorization": "Bearer sk_setu_not_a_real_key"},
    )
    assert resp.status_code == 401
