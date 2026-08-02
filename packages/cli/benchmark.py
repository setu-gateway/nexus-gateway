import asyncio
import statistics
import time
from dataclasses import dataclass, field

import httpx

# Each provider's catalog-primary model (apps/gateway/models/catalog.py) - requesting it
# directly exercises the real /v1/chat/completions path end-to-end (routing included)
# rather than a synthetic bypass, since the router prefers the primary candidate when
# everything's healthy.
DEFAULT_MODEL_BY_PROVIDER = {
    "openai": "gpt-4o",
    "anthropic": "claude-3-5-sonnet",
    "gemini": "gemini-1.5-pro",
    "groq": "groq-llama-3.3",
    "ollama": "llama3",
}


@dataclass
class RequestOutcome:
    success: bool
    latency_ms: float
    time_to_first_chunk_ms: float | None = None
    error: str | None = None


@dataclass
class ProviderBenchmarkResult:
    provider: str
    model: str
    outcomes: list[RequestOutcome] = field(default_factory=list)
    throughput_rps: float = 0.0

    @property
    def success_count(self) -> int:
        return sum(1 for o in self.outcomes if o.success)

    @property
    def error_rate(self) -> float:
        if not self.outcomes:
            return 0.0
        return round((1 - self.success_count / len(self.outcomes)) * 100, 2)

    @property
    def _latencies(self) -> list[float]:
        return sorted(o.latency_ms for o in self.outcomes if o.success)

    @property
    def avg_latency_ms(self) -> float:
        lat = self._latencies
        return round(statistics.mean(lat), 2) if lat else 0.0

    def percentile_latency_ms(self, pct: float) -> float:
        lat = self._latencies
        if not lat:
            return 0.0
        idx = min(len(lat) - 1, int(len(lat) * pct))
        return lat[idx]

    @property
    def avg_time_to_first_chunk_ms(self) -> float | None:
        values = [o.time_to_first_chunk_ms for o in self.outcomes if o.success and o.time_to_first_chunk_ms is not None]
        return round(statistics.mean(values), 2) if values else None


async def _run_single_request(client: httpx.AsyncClient, base_url: str, model: str, prompt: str, stream: bool) -> RequestOutcome:
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": stream}
    start = time.perf_counter()
    try:
        if stream:
            first_chunk_at: float | None = None
            async with client.stream("POST", f"{base_url}/v1/chat/completions", json=payload, timeout=30.0) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes():
                    if chunk and first_chunk_at is None:
                        first_chunk_at = time.perf_counter()
            end = time.perf_counter()
            return RequestOutcome(
                success=True,
                latency_ms=round((end - start) * 1000, 2),
                time_to_first_chunk_ms=round((first_chunk_at - start) * 1000, 2) if first_chunk_at else None,
            )

        resp = await client.post(f"{base_url}/v1/chat/completions", json=payload, timeout=30.0)
        resp.raise_for_status()
        return RequestOutcome(success=True, latency_ms=round((time.perf_counter() - start) * 1000, 2))
    except Exception as e:
        return RequestOutcome(success=False, latency_ms=round((time.perf_counter() - start) * 1000, 2), error=str(e))


async def benchmark_provider(
    base_url: str,
    provider: str,
    model: str,
    prompt: str,
    requests: int,
    concurrency: int,
    stream: bool,
) -> ProviderBenchmarkResult:
    """Fire `requests` calls at a provider's model with bounded concurrency, measuring
    latency, throughput (successful requests / wall-clock duration), and - for
    streaming - time to first chunk."""
    result = ProviderBenchmarkResult(provider=provider, model=model)
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _bounded(client: httpx.AsyncClient) -> RequestOutcome:
        async with semaphore:
            return await _run_single_request(client, base_url, model, prompt, stream)

    wall_start = time.perf_counter()
    async with httpx.AsyncClient() as client:
        result.outcomes = list(await asyncio.gather(*[_bounded(client) for _ in range(requests)]))
    wall_duration_sec = time.perf_counter() - wall_start

    result.throughput_rps = round(result.success_count / wall_duration_sec, 2) if wall_duration_sec > 0 else 0.0
    return result


async def run_benchmark(
    base_url: str,
    providers: list[str],
    requests: int = 10,
    concurrency: int = 3,
    stream: bool = False,
    prompt: str = "Summarize what an AI gateway does in one sentence.",
) -> list[ProviderBenchmarkResult]:
    results = []
    for provider in providers:
        model = DEFAULT_MODEL_BY_PROVIDER.get(provider, provider)
        results.append(await benchmark_provider(base_url, provider, model, prompt, requests, concurrency, stream))
    return results
