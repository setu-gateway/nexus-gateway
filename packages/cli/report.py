from packages.cli.benchmark import ProviderBenchmarkResult


def render_table(headers: list[str], rows: list[list[str]]) -> str:
    """Aligned plain-text table shared by every CLI subcommand that reports tabular
    data - useful for pasting into documentation, a PR description, or a terminal."""
    widths = [max(len(headers[i]), *(len(row[i]) for row in rows)) if rows else len(headers[i]) for i in range(len(headers))]

    def _fmt_row(cells: list[str]) -> str:
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells))

    lines = [_fmt_row(headers), _fmt_row(["-" * w for w in widths])]
    lines.extend(_fmt_row(row) for row in rows)
    return "\n".join(lines)


def render_benchmark_report(results: list[ProviderBenchmarkResult], stream: bool) -> str:
    """Render benchmark results as an aligned plain-text table - useful for pasting
    into documentation or a PR description, per Epic 4.10's stated purpose."""
    headers = ["Provider", "Model", "Avg", "p95", "Throughput", "Errors"]
    if stream:
        headers.insert(3, "TTFC")

    rows = []
    for r in results:
        row = [
            r.provider,
            r.model,
            f"{r.avg_latency_ms:.0f}ms",
            f"{r.percentile_latency_ms(0.95):.0f}ms",
            f"{r.throughput_rps:.2f} req/s",
            f"{r.error_rate:.1f}%",
        ]
        if stream:
            ttfc = r.avg_time_to_first_chunk_ms
            row.insert(3, f"{ttfc:.0f}ms" if ttfc is not None else "—")
        rows.append(row)

    lines = [render_table(headers, rows)]

    failing = [r for r in results if r.error_rate > 0]
    if failing:
        lines.append("")
        lines.append("Errors:")
        for r in failing:
            sample_error = next((o.error for o in r.outcomes if o.error), "unknown error")
            lines.append(f"  {r.provider}: {sample_error}")

    return "\n".join(lines)
