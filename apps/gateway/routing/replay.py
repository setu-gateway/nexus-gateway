import asyncio
import time
from typing import Any

from pydantic import BaseModel

from apps.gateway.providers.registry import ProviderRegistry
from packages.plugin_sdk import ChatRequest


class ReplayResult(BaseModel):
    """One provider's outcome from replaying the same request (Request Replay
    feature) - used for testing, regression analysis, and side-by-side provider
    comparison. Deliberately not recorded to request_logs/analytics: this is a
    diagnostic tool, not production traffic."""

    provider: str
    upstream_model: str
    success: bool
    latency_ms: float
    response: dict[str, Any] | None = None
    error: str | None = None


async def replay_request(
    provider_registry: ProviderRegistry,
    candidates: list[tuple[str, str]],
    messages: list[dict[str, Any]],
    temperature: float | None = 0.7,
    top_p: float | None = 1.0,
    max_tokens: int | None = None,
) -> list[ReplayResult]:
    """Run the same messages against every (provider, upstream_model) pair in
    `candidates` concurrently, returning each outcome independently - one provider
    erroring never affects the others' results."""

    async def _replay_one(provider_name: str, upstream_model: str) -> ReplayResult:
        provider = provider_registry.get_provider(provider_name)
        if not provider:
            return ReplayResult(
                provider=provider_name,
                upstream_model=upstream_model,
                success=False,
                latency_ms=0.0,
                error=f"Provider '{provider_name}' is not enabled",
            )

        chat_req = ChatRequest(
            model=upstream_model,
            messages=messages,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            stream=False,
        )
        start = time.perf_counter()
        try:
            response = await provider.chat(chat_req)
            return ReplayResult(
                provider=provider_name,
                upstream_model=upstream_model,
                success=True,
                latency_ms=round((time.perf_counter() - start) * 1000, 2),
                response=response if isinstance(response, dict) else {"result": str(response)},
            )
        except Exception as e:
            return ReplayResult(
                provider=provider_name,
                upstream_model=upstream_model,
                success=False,
                latency_ms=round((time.perf_counter() - start) * 1000, 2),
                error=str(e),
            )

    return list(await asyncio.gather(*[_replay_one(p, m) for p, m in candidates]))
