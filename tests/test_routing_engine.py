from apps.gateway.api.openai_v1 import ChatCompletionMessage, _detects_vision_request
from apps.gateway.models.catalog import ModelRegistry
from apps.gateway.providers.health_monitor import ProviderHealthMonitor
from apps.gateway.providers.registry import ProviderRegistry
from apps.gateway.routing.config import RoutingConfig
from apps.gateway.routing.engine import NoHealthyProviderError, RoutingEngine
from apps.gateway.routing.policies import RoutingPolicy
import pytest


class _FakeProvider:
    """Duck-typed stand-in for a ProviderPlugin - the routing engine only ever asks
    the registry whether a name is enabled, never calls provider methods directly."""

    def __init__(self, name: str):
        self.provider_name = name
        self.name = name


def _make_engine(config=None, rng=None, enabled=("openai", "gemini", "ollama", "groq")):
    # anthropic disabled by default, matching packages/shared/config/providers_config.py's
    # real production default - keeps candidate sets in these tests predictable.
    model_registry = ModelRegistry()
    provider_registry = ProviderRegistry()
    for name in ("openai", "anthropic", "gemini", "ollama", "groq"):
        provider_registry.register_provider(_FakeProvider(name), enabled=name in enabled)
    health_monitor = ProviderHealthMonitor(provider_registry)
    import random

    engine = RoutingEngine(model_registry, provider_registry, health_monitor, config=config, rng=rng or random)
    return engine, model_registry, provider_registry, health_monitor


def test_route_picks_catalog_primary_when_all_else_equal():
    engine, *_ = _make_engine()
    decision = engine.route("gpt-4o")
    assert decision.selected_provider == "openai"
    assert decision.selected_upstream_model == "gpt-4o"
    assert decision.fallback_used is False
    assert decision.routing_policy == RoutingPolicy.HIGHEST_AVAILABILITY.value


def test_route_unknown_model_falls_back_to_openai_passthrough():
    engine, *_ = _make_engine()
    decision = engine.route("some-custom-finetune-not-in-catalog")
    assert decision.selected_provider == "openai"
    assert decision.selected_upstream_model == "some-custom-finetune-not-in-catalog"
    assert decision.estimated_cost == 0.0


def test_route_raises_when_no_provider_is_enabled():
    engine, *_ = _make_engine(enabled=())
    with pytest.raises(NoHealthyProviderError):
        engine.route("gpt-4o")


def test_lowest_latency_policy_prefers_faster_equivalent():
    engine, _, _, health_monitor = _make_engine()
    health_monitor.record_request_result("openai", success=True, latency_ms=900)
    health_monitor.record_request_result("gemini", success=True, latency_ms=50)

    decision = engine.route("gpt-4o", policy=RoutingPolicy.LOWEST_LATENCY)
    assert decision.selected_provider == "gemini"
    assert decision.fallback_used is True
    assert "latency" in decision.selection_reason.lower()


def test_lowest_cost_policy_prefers_cheaper_equivalent():
    engine, *_ = _make_engine()
    # gpt-4o ($0.0025 in / $0.01 out) vs its equivalent gemini-1.5-pro ($0.00125 / $0.005).
    decision = engine.route("gpt-4o", policy=RoutingPolicy.LOWEST_COST)
    assert decision.selected_provider == "gemini"
    assert decision.estimated_cost < engine.model_registry.get_model("gpt-4o").estimate_cost(1000, 500)


def test_highest_availability_policy_avoids_degraded_provider():
    engine, _, _, health_monitor = _make_engine()
    for _ in range(10):
        health_monitor.record_request_result("openai", success=False, latency_ms=100)
    health_monitor.record_request_result("gemini", success=True, latency_ms=100)

    decision = engine.route("gpt-4o", policy=RoutingPolicy.HIGHEST_AVAILABILITY)
    assert decision.selected_provider == "gemini"


def test_offline_provider_excluded_from_selection_but_shown_for_transparency():
    engine, _, _, health_monitor = _make_engine()
    for _ in range(10):
        health_monitor.record_request_result("openai", success=False, latency_ms=100)
    assert health_monitor.get_metrics("openai").status == "offline"

    decision = engine.route("gpt-4o")
    assert decision.selected_provider != "openai"
    assert decision.fallback_used is True

    considered = {c.provider_name: c for c in decision.candidates}
    assert "openai" in considered
    assert considered["openai"].healthy is False


def test_user_preference_policy_respects_configured_default():
    engine, *_ = _make_engine(config=RoutingConfig(preferred_provider="gemini"))
    decision = engine.route("gpt-4o", policy=RoutingPolicy.USER_PREFERENCE)
    assert decision.selected_provider == "gemini"
    assert "default provider" in decision.selection_reason.lower()


def test_user_preference_policy_degrades_gracefully_when_preference_not_a_candidate():
    engine, *_ = _make_engine(config=RoutingConfig(preferred_provider="groq"))
    # groq's catalog model isn't a "flagship" tier equivalent of gpt-4o, so it's never a
    # candidate here - the policy should still return a valid decision, not crash.
    decision = engine.route("gpt-4o", policy=RoutingPolicy.USER_PREFERENCE)
    assert decision.selected_provider in ("openai", "gemini")


def test_round_robin_rotates_across_successive_requests():
    engine, *_ = _make_engine()
    seen = {engine.route("gpt-4o", policy=RoutingPolicy.ROUND_ROBIN).selected_provider for _ in range(4)}
    # With 2 healthy candidates (openai, gemini) and 4 turns, both must have been chosen.
    assert seen == {"openai", "gemini"}


def test_weighted_policy_uses_configured_weights_via_injected_rng():
    class _StubRng:
        def choices(self, candidates, weights, k):
            best_index = max(range(len(candidates)), key=lambda i: weights[i])
            return [candidates[best_index]]

    engine, *_ = _make_engine(config=RoutingConfig(weights={"openai": 10, "gemini": 90}), rng=_StubRng())
    decision = engine.route("gpt-4o", policy=RoutingPolicy.WEIGHTED)
    assert decision.selected_provider == "gemini"
    assert "weight 90" in decision.selection_reason


def test_weighted_policy_falls_back_to_equal_weights_when_unconfigured():
    class _StubRng:
        def choices(self, candidates, weights, k):
            assert weights == [1.0] * len(weights)
            return [candidates[0]]

    engine, *_ = _make_engine(rng=_StubRng())
    decision = engine.route("gpt-4o", policy=RoutingPolicy.WEIGHTED)
    assert decision.selected_provider in ("openai", "gemini")


def test_capability_based_routing_filters_to_vision_capable_providers():
    engine, *_ = _make_engine()
    decision = engine.route(
        "gpt-4o-mini", policy=RoutingPolicy.CAPABILITY_BASED, required_capability="vision"
    )
    # groq/ollama/anthropic's "fast" tier models don't support vision - only openai
    # (primary) and gemini's vision-capable equivalent should ever be considered.
    assert set(decision.fallback_chain) <= {"openai", "gemini"}


def test_explain_payload_lists_full_fallback_chain_in_order():
    engine, _, _, health_monitor = _make_engine()
    health_monitor.record_request_result("openai", success=True, latency_ms=500)
    health_monitor.record_request_result("gemini", success=True, latency_ms=20)

    decision = engine.route("gpt-4o", policy=RoutingPolicy.LOWEST_LATENCY)
    assert decision.fallback_chain[0] == "gemini"
    assert "openai" in decision.fallback_chain
    assert decision.request_id


def test_find_equivalents_unknown_model_returns_empty():
    registry = ModelRegistry()
    assert registry.find_equivalents("not-a-real-model") == []


def test_estimate_cost_is_zero_for_self_hosted_models():
    registry = ModelRegistry()
    llama = registry.get_model("llama3")
    assert llama.estimate_cost(input_tokens=100_000, output_tokens=50_000) == 0.0


def test_trust_score_offline_is_zero_and_healthy_is_high():
    monitor = ProviderHealthMonitor(ProviderRegistry())
    for _ in range(10):
        monitor.record_request_result("flaky", success=False, latency_ms=100)
    assert monitor.get_metrics("flaky").status == "offline"
    assert monitor.get_trust_score("flaky") == 0.0

    monitor.record_request_result("solid", success=True, latency_ms=50)
    assert monitor.get_trust_score("solid") > 80.0


def test_detects_vision_request_from_image_url_content_part():
    text_only = [ChatCompletionMessage(role="user", content="just text")]
    assert _detects_vision_request(text_only) is False

    with_image = [
        ChatCompletionMessage(
            role="user",
            content=[
                {"type": "text", "text": "what is this?"},
                {"type": "image_url", "image_url": {"url": "https://example.com/cat.png"}},
            ],
        )
    ]
    assert _detects_vision_request(with_image) is True
