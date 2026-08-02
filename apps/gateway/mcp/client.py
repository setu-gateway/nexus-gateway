import itertools
import json
from typing import Any

import httpx

_PROTOCOL_VERSION = "2025-03-26"
_REQUEST_TIMEOUT_SECONDS = 15.0
_id_counter = itertools.count(1)


class MCPError(Exception):
    """Raised for any MCP-level failure: transport error, non-2xx HTTP response, a
    JSON-RPC error reply, or a malformed response body. Callers see one exception
    type regardless of which of those occurred; the message says which - this is
    what apps/gateway/api/mcp.py turns into a 502 (the MCP server's problem, not the
    gateway's)."""


def _headers(server_headers: dict[str, str] | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if server_headers:
        headers.update(server_headers)
    return headers


def _parse_response_body(content_type: str, text: str) -> dict[str, Any]:
    """Parses a JSON-RPC response delivered either as a plain JSON body or as one or
    more `data: {...}` frames of a text/event-stream body - MCP's Streamable HTTP
    transport permits either for a single request/response exchange. When the body
    is an event stream, the LAST parsed frame is returned (the final message for
    this request; earlier frames, if any, would be intermediate notifications)."""
    if "text/event-stream" in content_type:
        last: dict[str, Any] | None = None
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[len("data:") :].strip()
            if not payload:
                continue
            try:
                last = json.loads(payload)
            except json.JSONDecodeError:
                continue
        if last is None:
            raise MCPError("Server returned an SSE stream with no parseable JSON-RPC message")
        return last

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise MCPError(f"Server response was not valid JSON: {e}") from e


async def _call_method(
    url: str, method: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None
) -> dict[str, Any]:
    """Sends one JSON-RPC 2.0 request and returns its `result`. Raises MCPError on
    any transport failure, non-2xx response, or a JSON-RPC-level error reply.

    Scope note (strategic foundation): this treats every call as its own
    request/response exchange rather than maintaining a persistent MCP session -
    server-initiated notifications, long-lived SSE streams, and session-scoped state
    are out of scope here. `initialize` is sent ahead of every operation (see
    list_tools/call_tool/check_health below) instead of once per session, which is a
    safe, spec-legal simplification for a stateless HTTP gateway client and works
    against any MCP server that doesn't require session continuity across separate
    connections.
    """
    request_id = next(_id_counter)
    payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}

    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(url, json=payload, headers=_headers(headers))
    except httpx.HTTPError as e:
        raise MCPError(f"Could not reach MCP server: {e}") from e

    if response.status_code >= 400:
        raise MCPError(f"MCP server returned HTTP {response.status_code}: {response.text[:500]}")

    body = _parse_response_body(response.headers.get("content-type", ""), response.text)

    if "error" in body:
        error = body.get("error") or {}
        raise MCPError(f"MCP error {error.get('code', '?')}: {error.get('message', 'unknown error')}")
    if "result" not in body:
        raise MCPError("MCP response had neither 'result' nor 'error'")
    return body["result"]


def _initialize_params() -> dict[str, Any]:
    return {
        "protocolVersion": _PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": "setu-gateway", "version": "0.1.0"},
    }


async def check_health(url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    """Sends `initialize` and returns the server's advertised info/capabilities.
    Doubles as a protocol-compliance check, not just a reachability one: a URL that
    responds but doesn't speak MCP fails here with a clear MCPError instead of
    reporting healthy."""
    return await _call_method(url, "initialize", _initialize_params(), headers)


async def list_tools(url: str, headers: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Returns the server's advertised tools (`{name, description, inputSchema}` each,
    per the MCP spec)."""
    await _call_method(url, "initialize", _initialize_params(), headers)
    result = await _call_method(url, "tools/list", {}, headers)
    tools = result.get("tools")
    if not isinstance(tools, list):
        raise MCPError("tools/list response did not include a 'tools' array")
    return tools


async def call_tool(url: str, tool_name: str, arguments: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
    """Invokes `tool_name` and returns the server's result (`{content: [...],
    isError: bool}` per the MCP spec - a tool-level failure is reported this way,
    not as a JSON-RPC error, so it's returned here rather than raised)."""
    await _call_method(url, "initialize", _initialize_params(), headers)
    return await _call_method(url, "tools/call", {"name": tool_name, "arguments": arguments}, headers)
