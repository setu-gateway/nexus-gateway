from typing import List, Optional
import argparse
import asyncio
import sys

from packages.cli.benchmark import DEFAULT_MODEL_BY_PROVIDER, run_benchmark
from packages.cli.report import render_benchmark_report

DEFAULT_PROVIDERS = ["openai", "gemini", "groq", "ollama"]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="setu", description="Setu Gateway command-line tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bench = subparsers.add_parser("benchmark", help="Compare provider latency, throughput, and error rate")
    bench.add_argument("--url", default="http://localhost:8000", help="Gateway base URL (default: %(default)s)")
    bench.add_argument(
        "--providers",
        default=",".join(DEFAULT_PROVIDERS),
        help=f"Comma-separated provider names to benchmark. Known: {', '.join(DEFAULT_MODEL_BY_PROVIDER)}",
    )
    bench.add_argument("--requests", type=int, default=10, help="Requests per provider (default: %(default)s)")
    bench.add_argument("--concurrency", type=int, default=3, help="Max concurrent requests per provider (default: %(default)s)")
    bench.add_argument("--stream", action="store_true", help="Benchmark streaming responses (adds time-to-first-chunk)")
    bench.add_argument("--prompt", default=None, help="Override the benchmark prompt")

    return parser


async def _run_benchmark_command(args: argparse.Namespace) -> int:
    providers = [p.strip().lower() for p in args.providers.split(",") if p.strip()]
    if not providers:
        print("No providers specified.", file=sys.stderr)
        return 1

    print(f"Benchmarking {', '.join(providers)} against {args.url} " f"({args.requests} requests, concurrency={args.concurrency}, stream={args.stream})...\n")

    kwargs = {"requests": args.requests, "concurrency": args.concurrency, "stream": args.stream}
    if args.prompt:
        kwargs["prompt"] = args.prompt

    results = await run_benchmark(args.url, providers, **kwargs)
    print(render_benchmark_report(results, stream=args.stream))

    return 1 if any(r.error_rate == 100.0 for r in results) else 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "benchmark":
        return asyncio.run(_run_benchmark_command(args))

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
