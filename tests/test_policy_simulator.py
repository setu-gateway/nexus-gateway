import random
import uuid

from fastapi.testclient import TestClient
import pytest

from apps.gateway.main import app
from apps.gateway.models.catalog import ModelRegistry
from apps.gateway.providers.health_monitor import ProviderHealthMonitor
from apps.gateway.providers.registry import ProviderRegistry
from apps.gateway.routing.engine import RoutingEngine
from apps.gateway.routing.policies import RoutingPolicy
from apps.gateway.routing.simulator import default_simulation_sample, simulate_policy

client = TestClient(app)


class _FakeProvider:
    def __init__(self, name):
        self.provider_name = name
        self.name = name


def _make_engine():
    model_registry = ModelRegistry()
    provider_registry = ProviderRegistry()
    for name in ("openai", "gemini", "ollama", "groq"):
        provider_registry.register_provider(_FakeProvider(name), enabled=True)
    health_monitor = ProviderHealthMonitor(provider_registry)
    return RoutingEngine(model_registry, provider_registry, health_monitor, rng=random)


def test_simulate_policy_never_mutates_the_live_engines_round_robin_state():
    engine = _make_engine()
    assert engine._round_robin_counters == {}

    simulate_policy(engine, RoutingPolicy.ROUND_ROBIN, ["gpt-4o"] * 20, trials_per_model=1)

    # The whole point of the simulator: real traffic's round-robin rotation must be
    # completely unaffected by having run a simulation.
    assert engine._round_robin_counters == {}


def test_simulate_policy_deterministic_lowest_cost_is_consistent():
    engine = _make_engine()
    outcome = simulate_policy(engine, RoutingPolicy.LOWEST_COST, ["gpt-4o"] * 10)
    assert outcome.sample_size == 10
    # Deterministic policy against an unchanging health snapshot -> one clear winner.
    assert len(outcome.provider_distribution) == 1
    assert sum(outcome.provider_distribution.values()) == pytest.approx(100.0)


def test_simulate_policy_weighted_reflects_configured_weights():
    from apps.gateway.routing.config import RoutingConfig

    provider_registry = ProviderRegistry()
    provider_registry.register_provider(_FakeProvider("openai"), enabled=True)
    provider_registry.register_provider(_FakeProvider("gemini"), enabled=True)
    health_monitor = ProviderHealthMonitor(provider_registry)

    engine = RoutingEngine(
        ModelRegistry(),
        provider_registry,
        health_monitor,
        config=RoutingConfig(weights={"openai": 90, "gemini": 10}),
        rng=random,
    )

    outcome = simulate_policy(engine, RoutingPolicy.WEIGHTED, ["gpt-4o"] * 200)
    assert outcome.sample_size == 200
    # Statistically openai should dominate; allow generous slack to avoid test flakiness.
    assert outcome.provider_distribution.get("openai", 0) > outcome.provider_distribution.get("gemini", 0)


def test_simulate_policy_across_mixed_models_can_split_across_providers():
    engine = _make_engine()
    # gpt-4o (flagship, openai primary) and gpt-4o-mini (fast, openai primary) both
    # exist, but their tier-equivalents differ - lowest_cost per-model can legitimately
    # land on different providers depending on which tier is cheaper elsewhere.
    outcome = simulate_policy(engine, RoutingPolicy.LOWEST_COST, ["gpt-4o", "gpt-4o-mini", "text-embedding-3-small"])
    assert outcome.sample_size == 3
    assert set(outcome.sample_models) == {"gpt-4o", "gpt-4o-mini", "text-embedding-3-small"}


def test_default_simulation_sample_uses_recent_models_when_provided():
    engine = _make_engine()
    assert default_simulation_sample(engine, recent_models=["gpt-4o", "gpt-4o"]) == ["gpt-4o", "gpt-4o"]


def test_default_simulation_sample_falls_back_to_full_catalog():
    engine = _make_engine()
    sample = default_simulation_sample(engine, recent_models=None)
    assert "gpt-4o" in sample
    assert len(sample) == len(engine.model_registry.list_models())


def test_simulate_endpoint_returns_distribution():
    resp = client.post("/routing/simulate", json={"policy": "lowest_cost", "models": ["gpt-4o", "gpt-4o-mini"]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["sample_size"] == 2
    assert data["policy"] == "lowest_cost"
    assert isinstance(data["provider_distribution"], dict)


def test_simulate_endpoint_falls_back_to_recent_request_history():
    # Generate some real traffic so the endpoint has history to sample from.
    client.post("/v1/chat/completions", json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]})

    resp = client.post("/routing/simulate", json={"policy": "highest_availability"})
    assert resp.status_code == 200
    assert resp.json()["sample_size"] >= 1


def test_simulate_endpoint_rejects_invalid_policy_name():
    resp = client.post("/routing/simulate", json={"policy": "not_a_real_policy"})
    assert resp.status_code == 422
