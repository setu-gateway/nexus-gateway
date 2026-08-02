from collections import Counter

from pydantic import BaseModel

from apps.gateway.routing.engine import NoHealthyProviderError, RoutingEngine
from apps.gateway.routing.policies import RoutingPolicy


class SimulationOutcome(BaseModel):
    """Result of simulating a routing policy against a sample of requests, without
    touching production traffic or state (Policy Simulator feature)."""

    policy: str
    sample_size: int
    provider_distribution: dict[str, float]
    fallback_rate: float
    avg_estimated_cost: float
    avg_latency_ms: float
    sample_models: list[str]


def simulate_policy(
    routing_engine: RoutingEngine,
    policy: RoutingPolicy,
    models: list[str],
    trials_per_model: int = 1,
) -> SimulationOutcome:
    """Run `policy` against a sample of requested models and report the resulting
    provider distribution - "if we switched to this policy, here's roughly how traffic
    would split." No production traffic is affected: this always builds its own
    throwaway RoutingEngine sharing the live registries (so it sees real, current
    health/capacity data) but with fresh, isolated per-call state, so a simulated
    round-robin run can never advance the counters the live engine uses for real
    requests.
    """
    # Real randomness (the default `random` module), not whatever rng the live engine
    # may have been constructed with for its own tests - a simulation should reflect
    # genuine statistical variance, especially for the weighted policy.
    sim_engine = RoutingEngine(
        routing_engine.model_registry,
        routing_engine.provider_registry,
        routing_engine.health_monitor,
        config=routing_engine.config,
    )

    provider_counts: Counter = Counter()
    fallback_count = 0
    total_cost = 0.0
    total_latency = 0.0
    total = 0

    for model in models:
        for _ in range(max(1, trials_per_model)):
            try:
                decision = sim_engine.route(model, policy=policy)
            except NoHealthyProviderError:
                continue

            provider_counts[decision.selected_provider] += 1
            fallback_count += 1 if decision.fallback_used else 0
            total_cost += decision.estimated_cost
            selected = next((c for c in decision.candidates if c.provider_name == decision.selected_provider), None)
            total_latency += selected.latency_ms if selected else 0.0
            total += 1

    if total == 0:
        return SimulationOutcome(
            policy=policy.value,
            sample_size=0,
            provider_distribution={},
            fallback_rate=0.0,
            avg_estimated_cost=0.0,
            avg_latency_ms=0.0,
            sample_models=models,
        )

    distribution = {provider: round((count / total) * 100, 1) for provider, count in provider_counts.items()}

    return SimulationOutcome(
        policy=policy.value,
        sample_size=total,
        provider_distribution=distribution,
        fallback_rate=round((fallback_count / total) * 100, 1),
        avg_estimated_cost=round(total_cost / total, 6),
        avg_latency_ms=round(total_latency / total, 2),
        sample_models=models,
    )


def default_simulation_sample(routing_engine: RoutingEngine, recent_models: list[str] | None = None) -> list[str]:
    """Pick a representative sample of models to simulate against: real recent traffic
    when available (from request_logs, passed in by the caller), otherwise one of every
    catalog model so at least every tier/provider combination is represented."""
    if recent_models:
        return recent_models
    return [m.model_id for m in routing_engine.model_registry.list_models()]
