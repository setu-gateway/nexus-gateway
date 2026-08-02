import httpx
import pytest

from packages.cli.benchmark import benchmark_provider, run_benchmark
from packages.cli.main import _build_parser, main
from packages.cli.report import render_benchmark_report

_RealAsyncClient = httpx.AsyncClient  # captured before any test patches httpx.AsyncClient


def _mock_transport(*, fail: bool = False):
    def handler(request: httpx.Request) -> httpx.Response:
        if fail:
            return httpx.Response(500, json={"detail": "boom"})
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "model": "gpt-4o",
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            },
        )

    return httpx.MockTransport(handler)


def _patch_httpx_client(monkeypatch, transport: httpx.MockTransport) -> None:
    def _client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return _RealAsyncClient(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory)


@pytest.mark.asyncio
async def test_benchmark_provider_success_records_latencies(monkeypatch):
    _patch_httpx_client(monkeypatch, _mock_transport())

    result = await benchmark_provider("http://fake", "openai", "gpt-4o", "hi", requests=4, concurrency=2, stream=False)
    assert result.success_count == 4
    assert result.error_rate == 0.0
    assert result.avg_latency_ms >= 0
    assert result.throughput_rps > 0


@pytest.mark.asyncio
async def test_benchmark_provider_records_errors(monkeypatch):
    _patch_httpx_client(monkeypatch, _mock_transport(fail=True))

    result = await benchmark_provider("http://fake", "openai", "gpt-4o", "hi", requests=3, concurrency=1, stream=False)
    assert result.success_count == 0
    assert result.error_rate == 100.0
    assert result.outcomes[0].error is not None


@pytest.mark.asyncio
async def test_run_benchmark_covers_multiple_providers(monkeypatch):
    _patch_httpx_client(monkeypatch, _mock_transport())

    results = await run_benchmark("http://fake", ["openai", "ollama"], requests=2, concurrency=1)
    assert [r.provider for r in results] == ["openai", "ollama"]
    assert results[0].model == "gpt-4o"
    assert results[1].model == "llama3"


def test_render_benchmark_report_includes_all_providers_and_error_detail():
    from packages.cli.benchmark import ProviderBenchmarkResult, RequestOutcome

    good = ProviderBenchmarkResult(
        provider="openai",
        model="gpt-4o",
        outcomes=[RequestOutcome(success=True, latency_ms=10.0)],
        throughput_rps=5.0,
    )
    bad = ProviderBenchmarkResult(
        provider="groq",
        model="groq-llama-3.3",
        outcomes=[RequestOutcome(success=False, latency_ms=1.0, error="connection refused")],
        throughput_rps=0.0,
    )

    report = render_benchmark_report([good, bad], stream=False)
    assert "openai" in report
    assert "groq" in report
    assert "100.0%" in report  # groq's error rate
    assert "connection refused" in report


def test_render_benchmark_report_includes_ttfc_column_when_streaming():
    from packages.cli.benchmark import ProviderBenchmarkResult, RequestOutcome

    result = ProviderBenchmarkResult(
        provider="openai",
        model="gpt-4o",
        outcomes=[RequestOutcome(success=True, latency_ms=50.0, time_to_first_chunk_ms=12.0)],
        throughput_rps=2.0,
    )
    report = render_benchmark_report([result], stream=True)
    assert "TTFC" in report
    assert "12ms" in report


def test_cli_parser_defaults():
    parser = _build_parser()
    args = parser.parse_args(["benchmark"])
    assert args.command == "benchmark"
    assert args.url == "http://localhost:8000"
    assert args.requests == 10
    assert args.concurrency == 3
    assert args.stream is False


def test_cli_parser_custom_flags():
    parser = _build_parser()
    args = parser.parse_args(["benchmark", "--url", "http://example.com", "--providers", "openai,groq", "--requests", "5", "--stream"])
    assert args.url == "http://example.com"
    assert args.providers == "openai,groq"
    assert args.requests == 5
    assert args.stream is True


def test_main_runs_benchmark_end_to_end(monkeypatch, capsys):
    _patch_httpx_client(monkeypatch, _mock_transport())

    exit_code = main(["benchmark", "--providers", "openai", "--requests", "1", "--concurrency", "1"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "openai" in captured.out
