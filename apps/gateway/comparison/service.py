from dataclasses import dataclass
from typing import Any

from apps.gateway.models.catalog import ModelRegistry
from apps.gateway.providers.registry import ProviderRegistry
from apps.gateway.routing.replay import ReplayResult, replay_request


@dataclass
class ComparisonCandidateResult:
    """One requested model's outcome within a comparison - ReplayResult enriched with
    the unified model id it was requested as, its extracted response text, and its
    real cost/token usage (ReplayResult itself stays provider/upstream-model shaped,
    since Epic 4's replay tool has no concept of "unified model" or pricing)."""

    model: str
    provider: str
    upstream_model: str
    success: bool
    latency_ms: float
    response_text: str | None
    cost_usd: float | None
    prompt_tokens: int | None
    completion_tokens: int | None
    error: str | None


def _extract_text(response: dict[str, Any] | None) -> str | None:
    if not response:
        return None
    try:
        content = response["choices"][0]["message"].get("content")
        return content if isinstance(content, str) else None
    except (KeyError, IndexError, TypeError):
        return None


def _enrich(model_id: str, result: ReplayResult, model_registry: ModelRegistry) -> ComparisonCandidateResult:
    usage = (result.response or {}).get("usage") if isinstance(result.response, dict) else None
    prompt_tokens = usage.get("prompt_tokens") if isinstance(usage, dict) else None
    completion_tokens = usage.get("completion_tokens") if isinstance(usage, dict) else None

    cost_usd = None
    model_def = model_registry.get_model(model_id)
    if model_def and isinstance(prompt_tokens, int) and isinstance(completion_tokens, int):
        cost_usd = model_def.estimate_cost(prompt_tokens, completion_tokens)

    return ComparisonCandidateResult(
        model=model_id,
        provider=result.provider,
        upstream_model=result.upstream_model,
        success=result.success,
        latency_ms=result.latency_ms,
        response_text=_extract_text(result.response),
        cost_usd=cost_usd,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        error=result.error,
    )


async def run_comparison(
    provider_registry: ProviderRegistry,
    model_registry: ModelRegistry,
    models: list[str],
    messages: list[dict[str, Any]],
    temperature: float | None = 0.7,
    top_p: float | None = 1.0,
    max_tokens: int | None = None,
) -> list[ComparisonCandidateResult]:
    """Runs the same messages against every model in `models` concurrently (via Epic
    4's replay_request, reused rather than reimplemented) and enriches each outcome
    with cost/token data for side-by-side comparison. Each entry of `models` is a
    unified catalog model id (e.g. "gpt-4o", "claude-3-5-sonnet") and may name any
    mix of providers - unlike /routing/replay, which compares one model's
    provider-equivalents, this compares independently-chosen models directly.
    """
    candidates = [model_registry.resolve_provider_model(m) for m in models]
    results = await replay_request(provider_registry, candidates, messages, temperature=temperature, top_p=top_p, max_tokens=max_tokens)
    return [_enrich(model_id, result, model_registry) for model_id, result in zip(models, results, strict=True)]
