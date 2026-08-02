import argparse
import asyncio
import sys
from typing import Any

from packages.cli.benchmark import DEFAULT_MODEL_BY_PROVIDER, run_benchmark
from packages.cli.doctor import DoctorCheck, run_config_checks, run_doctor_checks
from packages.cli.gateway_ops import clear_cache, fetch_health, fetch_providers, replay_prompt
from packages.cli.report import render_benchmark_report, render_table

DEFAULT_PROVIDERS = ["openai", "gemini", "groq", "ollama"]
DEFAULT_URL = "http://localhost:8000"


def _extract_message_text(response_body: dict[str, Any]) -> str:
    try:
        return response_body["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return str(response_body)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="setu", description="Setu Gateway command-line tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bench = subparsers.add_parser("benchmark", help="Compare provider latency, throughput, and error rate")
    bench.add_argument("--url", default=DEFAULT_URL, help="Gateway base URL (default: %(default)s)")
    bench.add_argument(
        "--providers",
        default=",".join(DEFAULT_PROVIDERS),
        help=f"Comma-separated provider names to benchmark. Known: {', '.join(DEFAULT_MODEL_BY_PROVIDER)}",
    )
    bench.add_argument("--requests", type=int, default=10, help="Requests per provider (default: %(default)s)")
    bench.add_argument("--concurrency", type=int, default=3, help="Max concurrent requests per provider (default: %(default)s)")
    bench.add_argument("--stream", action="store_true", help="Benchmark streaming responses (adds time-to-first-chunk)")
    bench.add_argument("--prompt", default=None, help="Override the benchmark prompt")

    doctor = subparsers.add_parser("doctor", help="Diagnose local setup: .env, settings, provider config, gateway reachability")
    doctor.add_argument("--url", default=DEFAULT_URL, help="Gateway base URL to check reachability against (default: %(default)s)")

    providers = subparsers.add_parser("providers", help="List configured providers with live health/trust metrics")
    providers.add_argument("--url", default=DEFAULT_URL, help="Gateway base URL (default: %(default)s)")

    health = subparsers.add_parser("health", help="Check gateway health (database, Redis)")
    health.add_argument("--url", default=DEFAULT_URL, help="Gateway base URL (default: %(default)s)")

    config = subparsers.add_parser("config", help="Local configuration commands")
    config_sub = config.add_subparsers(dest="config_command", required=True)
    config_sub.add_parser("validate", help="Validate .env/settings and provider config without a running gateway")

    replay = subparsers.add_parser("replay", help="Replay a prompt against one or more providers for comparison")
    replay.add_argument("--url", default=DEFAULT_URL, help="Gateway base URL (default: %(default)s)")
    replay.add_argument("--model", default=None, help="Unified model id to resolve candidate providers from")
    replay.add_argument("--providers", default=None, help="Comma-separated explicit provider list, overriding --model resolution")
    replay.add_argument("--prompt", default="Summarize what an AI gateway does in one sentence.", help="Prompt to replay")

    cache = subparsers.add_parser("cache", help="Cache management commands")
    cache_sub = cache.add_subparsers(dest="cache_command", required=True)
    cache_clear = cache_sub.add_parser("clear", help="Invalidate cached responses")
    cache_clear.add_argument("--url", default=DEFAULT_URL, help="Gateway base URL (default: %(default)s)")
    cache_clear.add_argument("--project-id", default=None, help="Clear only this project's entries (default: clear everything)")

    return parser


async def _run_benchmark_command(args: argparse.Namespace) -> int:
    providers = [p.strip().lower() for p in args.providers.split(",") if p.strip()]
    if not providers:
        print("No providers specified.", file=sys.stderr)
        return 1

    print(
        f"Benchmarking {', '.join(providers)} against {args.url} "
        f"({args.requests} requests, concurrency={args.concurrency}, stream={args.stream})...\n"
    )

    kwargs = {"requests": args.requests, "concurrency": args.concurrency, "stream": args.stream}
    if args.prompt:
        kwargs["prompt"] = args.prompt

    results = await run_benchmark(args.url, providers, **kwargs)
    print(render_benchmark_report(results, stream=args.stream))

    return 1 if any(r.error_rate == 100.0 for r in results) else 0


def _print_checks(checks: list[DoctorCheck]) -> int:
    for check in checks:
        marker = "[OK]  " if check.ok else "[FAIL]"
        line = f"{marker} {check.name}"
        if check.detail:
            line += f" - {check.detail}"
        print(line)
    return 0 if all(c.ok for c in checks) else 1


async def _run_doctor_command(args: argparse.Namespace) -> int:
    print(f"Running Setu Gateway diagnostics (gateway URL: {args.url})...\n")
    checks = await run_doctor_checks(args.url)
    return _print_checks(checks)


def _run_config_validate_command(args: argparse.Namespace) -> int:
    print("Validating local configuration...\n")
    return _print_checks(run_config_checks())


async def _run_providers_command(args: argparse.Namespace) -> int:
    try:
        providers = await fetch_providers(args.url)
    except Exception as e:
        print(f"Could not reach gateway at {args.url}: {e}", file=sys.stderr)
        return 1

    if not providers:
        print("No providers registered.")
        return 0

    headers = ["Provider", "Enabled", "Status", "Trust", "Latency", "Success Rate", "Models"]
    rows = [
        [
            p["name"],
            "yes" if p["enabled"] else "no",
            p["status"],
            f"{p['trust_score']:.2f}" if p["trust_score"] is not None else "—",
            f"{p['latency_ms']:.0f}ms" if p["latency_ms"] is not None else "—",
            f"{p['success_rate']:.1f}%" if p["success_rate"] is not None else "—",
            str(p["models"]),
        ]
        for p in providers
    ]
    print(render_table(headers, rows))
    return 0


async def _run_health_command(args: argparse.Namespace) -> int:
    try:
        result = await fetch_health(args.url)
    except Exception as e:
        print(f"Could not reach gateway at {args.url}: {e}", file=sys.stderr)
        return 1

    body = result["body"]
    print(f"status: {body.get('status')}")
    print(f"service: {body.get('service')}")
    for component, ok in body.get("components", {}).items():
        print(f"  {component}: {'ok' if ok else 'FAIL'}")
    return 0 if body.get("status") != "unhealthy" else 1


async def _run_replay_command(args: argparse.Namespace) -> int:
    providers = [p.strip().lower() for p in args.providers.split(",") if p.strip()] if args.providers else None
    if not args.model and not providers:
        print("Provide either --model or --providers.", file=sys.stderr)
        return 1

    try:
        result = await replay_prompt(args.url, model=args.model, providers=providers, prompt=args.prompt)
    except Exception as e:
        print(f"Replay failed: {e}", file=sys.stderr)
        return 1

    headers = ["Provider", "Model", "Success", "Latency", "Response / Error"]
    rows = []
    for r in result.get("results", []):
        content = _extract_message_text(r.get("response") or {})[:80] if r["success"] else r.get("error", "unknown error")
        rows.append(
            [
                r["provider"],
                r["upstream_model"],
                "yes" if r["success"] else "no",
                f"{r['latency_ms']:.0f}ms",
                content,
            ]
        )
    print(render_table(headers, rows))
    return 0 if all(r["success"] for r in result.get("results", [])) else 1


async def _run_cache_clear_command(args: argparse.Namespace) -> int:
    try:
        result = await clear_cache(args.url, project_id=args.project_id)
    except Exception as e:
        print(f"Cache clear failed: {e}", file=sys.stderr)
        return 1

    scope = f"project '{args.project_id}'" if args.project_id else "all projects"
    print(f"Cleared {result['cleared_entries']} cache entries ({scope}).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "benchmark":
        return asyncio.run(_run_benchmark_command(args))
    if args.command == "doctor":
        return asyncio.run(_run_doctor_command(args))
    if args.command == "providers":
        return asyncio.run(_run_providers_command(args))
    if args.command == "health":
        return asyncio.run(_run_health_command(args))
    if args.command == "config" and args.config_command == "validate":
        return _run_config_validate_command(args)
    if args.command == "replay":
        return asyncio.run(_run_replay_command(args))
    if args.command == "cache" and args.cache_command == "clear":
        return asyncio.run(_run_cache_clear_command(args))

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
