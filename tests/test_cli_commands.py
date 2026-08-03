import httpx
import pytest

from packages.cli.doctor import (
    check_env_file,
    check_gateway_reachable,
    check_providers_config,
    check_settings_load,
    run_config_checks,
)
from packages.cli.gateway_ops import clear_cache, fetch_health, fetch_providers, replay_prompt
from packages.cli.main import _build_parser, main

_RealAsyncClient = httpx.AsyncClient  # captured before any test patches httpx.AsyncClient


def _patch_httpx_client(monkeypatch, transport: httpx.MockTransport) -> None:
    def _client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return _RealAsyncClient(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory)


def _gateway_transport(*, unhealthy: bool = False, replay_fails: bool = False):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/health":
            if unhealthy:
                return httpx.Response(
                    503,
                    json={"status": "unhealthy", "service": "gateway", "components": {"database": False, "redis": False}},
                )
            return httpx.Response(200, json={"status": "ok", "service": "gateway", "components": {"database": True, "redis": True}})
        if path == "/providers":
            return httpx.Response(
                200,
                json=[
                    {"name": "openai", "provider_name": "openai", "enabled": True, "capabilities": {}, "models": ["gpt-4o", "gpt-4o-mini"]},
                    {"name": "ollama", "provider_name": "ollama", "enabled": False, "capabilities": {}, "models": ["llama3"]},
                ],
            )
        if path == "/providers/metrics/all":
            return httpx.Response(
                200,
                json=[
                    {
                        "provider_name": "openai",
                        "status": "online",
                        "trust_score": 95.5,
                        "latency_ms": 120.4,
                        "success_rate": 99.1,
                        "error_rate": 0.9,
                        "total_requests": 10,
                        "total_errors": 0,
                        "is_rate_limited": False,
                        "last_successful_request": None,
                    },
                    {
                        "provider_name": "ollama",
                        "status": "offline",
                        "trust_score": 0.0,
                        "latency_ms": None,
                        "success_rate": 0.0,
                        "error_rate": 0.0,
                        "total_requests": 0,
                        "total_errors": 0,
                        "is_rate_limited": False,
                        "last_successful_request": None,
                    },
                ],
            )
        if path == "/routing/replay":
            if replay_fails:
                return httpx.Response(
                    200,
                    json={
                        "results": [
                            {
                                "provider": "openai",
                                "upstream_model": "gpt-4o",
                                "success": False,
                                "latency_ms": 5.0,
                                "response": None,
                                "error": "boom",
                            }
                        ]
                    },
                )
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "provider": "openai",
                            "upstream_model": "gpt-4o",
                            "success": True,
                            "latency_ms": 42.0,
                            "response": {"choices": [{"message": {"content": "hi there"}}]},
                            "error": None,
                        }
                    ]
                },
            )
        if path == "/cache" and request.method == "DELETE":
            return httpx.Response(200, json={"cleared_entries": 3})
        return httpx.Response(404, json={"detail": "not found"})

    return httpx.MockTransport(handler)


# --- doctor.py checks ---


def test_check_env_file_reports_presence(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert check_env_file().ok is False

    (tmp_path / ".env").write_text("PORT=8000\n")
    assert check_env_file().ok is True


def test_check_settings_load_reports_current_environment():
    check = check_settings_load()
    assert check.ok is True
    assert "environment=" in check.detail


def test_check_providers_config_lists_enabled_providers():
    check = check_providers_config()
    assert check.ok is True
    assert "openai" in check.detail


@pytest.mark.asyncio
async def test_check_gateway_reachable_success(monkeypatch):
    _patch_httpx_client(monkeypatch, _gateway_transport())
    check = await check_gateway_reachable("http://fake")
    assert check.ok is True
    assert "status=ok" in check.detail


@pytest.mark.asyncio
async def test_check_gateway_reachable_unhealthy(monkeypatch):
    _patch_httpx_client(monkeypatch, _gateway_transport(unhealthy=True))
    check = await check_gateway_reachable("http://fake")
    assert check.ok is False


@pytest.mark.asyncio
async def test_check_gateway_reachable_connection_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    _patch_httpx_client(monkeypatch, httpx.MockTransport(handler))
    check = await check_gateway_reachable("http://fake")
    assert check.ok is False
    assert "refused" in check.detail


def test_run_config_checks_does_not_touch_the_network():
    checks = run_config_checks()
    assert {c.name for c in checks} == {"`.env` file present", "Settings load and validate", "Provider config loads correctly"}


# --- gateway_ops.py ---


@pytest.mark.asyncio
async def test_fetch_health(monkeypatch):
    _patch_httpx_client(monkeypatch, _gateway_transport())
    result = await fetch_health("http://fake")
    assert result["body"]["status"] == "ok"


@pytest.mark.asyncio
async def test_fetch_providers_merges_details_and_metrics(monkeypatch):
    _patch_httpx_client(monkeypatch, _gateway_transport())
    providers = await fetch_providers("http://fake")
    by_name = {p["name"]: p for p in providers}
    assert by_name["openai"]["enabled"] is True
    assert by_name["openai"]["trust_score"] == 95.5
    assert by_name["openai"]["models"] == 2
    assert by_name["ollama"]["status"] == "offline"


@pytest.mark.asyncio
async def test_replay_prompt_sends_model_and_returns_results(monkeypatch):
    _patch_httpx_client(monkeypatch, _gateway_transport())
    result = await replay_prompt("http://fake", model="gpt-4o", providers=None, prompt="hi")
    assert result["results"][0]["provider"] == "openai"


@pytest.mark.asyncio
async def test_clear_cache_returns_cleared_count(monkeypatch):
    _patch_httpx_client(monkeypatch, _gateway_transport())
    result = await clear_cache("http://fake", project_id=None)
    assert result["cleared_entries"] == 3


# --- argparse wiring ---


def test_cli_parser_doctor_and_health_default_url():
    parser = _build_parser()
    assert parser.parse_args(["doctor"]).url == "http://localhost:8000"
    assert parser.parse_args(["health"]).url == "http://localhost:8000"


def test_cli_parser_config_validate():
    parser = _build_parser()
    args = parser.parse_args(["config", "validate"])
    assert args.command == "config"
    assert args.config_command == "validate"


def test_cli_parser_cache_clear_with_project_id():
    parser = _build_parser()
    args = parser.parse_args(["cache", "clear", "--project-id", "proj-1"])
    assert args.cache_command == "clear"
    assert args.project_id == "proj-1"


def test_cli_parser_certify_with_and_without_provider():
    parser = _build_parser()
    assert parser.parse_args(["certify"]).provider is None
    assert parser.parse_args(["certify", "openai"]).provider == "openai"


def test_main_certify_lists_providers_when_none_given(capsys):
    assert main(["certify"]) == 0
    out = capsys.readouterr().out
    assert "openai" in out
    assert "ollama" in out


def test_main_certify_openai_end_to_end_exits_zero(capsys):
    assert main(["certify", "openai"]) == 0
    out = capsys.readouterr().out
    assert "CERTIFIED" in out


def test_main_certify_unknown_provider_exits_nonzero(capsys):
    assert main(["certify", "not-a-real-provider"]) == 1


def test_cli_parser_replay_options():
    parser = _build_parser()
    args = parser.parse_args(["replay", "--model", "gpt-4o", "--prompt", "hi"])
    assert args.model == "gpt-4o"
    assert args.prompt == "hi"


# --- main() end-to-end ---


def test_main_config_validate_exits_zero_on_success(capsys):
    exit_code = main(["config", "validate"])
    assert exit_code == 0
    assert "Settings load and validate" in capsys.readouterr().out


def test_main_doctor_reports_gateway_unreachable(monkeypatch, capsys):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    _patch_httpx_client(monkeypatch, httpx.MockTransport(handler))
    exit_code = main(["doctor", "--url", "http://fake"])
    assert exit_code == 1
    assert "[FAIL]" in capsys.readouterr().out


def test_main_health_end_to_end(monkeypatch, capsys):
    _patch_httpx_client(monkeypatch, _gateway_transport())
    exit_code = main(["health", "--url", "http://fake"])
    assert exit_code == 0
    assert "status: ok" in capsys.readouterr().out


def test_main_health_unhealthy_exits_nonzero(monkeypatch, capsys):
    _patch_httpx_client(monkeypatch, _gateway_transport(unhealthy=True))
    exit_code = main(["health", "--url", "http://fake"])
    assert exit_code == 1


def test_main_providers_end_to_end(monkeypatch, capsys):
    _patch_httpx_client(monkeypatch, _gateway_transport())
    exit_code = main(["providers", "--url", "http://fake"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "openai" in out
    assert "ollama" in out


def test_main_replay_end_to_end(monkeypatch, capsys):
    _patch_httpx_client(monkeypatch, _gateway_transport())
    exit_code = main(["replay", "--url", "http://fake", "--model", "gpt-4o", "--prompt", "hi"])
    assert exit_code == 0
    assert "hi there" in capsys.readouterr().out


def test_main_replay_reports_failure_and_exits_nonzero(monkeypatch, capsys):
    _patch_httpx_client(monkeypatch, _gateway_transport(replay_fails=True))
    exit_code = main(["replay", "--url", "http://fake", "--model", "gpt-4o"])
    assert exit_code == 1
    assert "boom" in capsys.readouterr().out


def test_main_replay_requires_model_or_providers(capsys):
    exit_code = main(["replay", "--url", "http://fake"])
    assert exit_code == 1
    assert "Provide either --model or --providers" in capsys.readouterr().err


def test_main_cache_clear_end_to_end(monkeypatch, capsys):
    _patch_httpx_client(monkeypatch, _gateway_transport())
    exit_code = main(["cache", "clear", "--url", "http://fake"])
    assert exit_code == 0
    assert "Cleared 3 cache entries" in capsys.readouterr().out
