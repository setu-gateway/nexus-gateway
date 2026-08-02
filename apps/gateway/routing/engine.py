import random
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from apps.gateway.models.catalog import ModelRegistry
from apps.gateway.providers.health_monitor import ProviderHealthMonitor
from apps.gateway.providers.registry import ProviderRegistry
from apps.gateway.routing.config import RoutingConfig, load_routing_config
from apps.gateway.routing.policies import RoutingPolicy
from apps.gateway.routing.rules import RuleActionType, RuleSpec, evaluate_rules
from packages.shared.logging.logger import get_logger

logger = get_logger("routing_engine")


class NoHealthyProviderError(Exception):
    """Raised when routing can't find any enabled, healthy candidate for a request."""


class RoutingRejectedError(Exception):
    """Raised when an org routing rule's action is 'reject' (Epic 4.2)."""


class RoutingCandidate(BaseModel):
    """A single provider/model option the router considered for a request."""

    provider_name: str
    upstream_model: str
    trust_score: float
    latency_ms: float
    estimated_cost: float
    is_primary: bool = False
    healthy: bool = True


class RoutingDecision(BaseModel):
    """Explainable routing outcome - this is the payload returned via the
    X-Setu-Routing-Debug response header when a request sends X-Setu-Debug: true (Epic 4.8)."""

    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    requested_model: str
    selected_provider: str
    selected_upstream_model: str
    routing_policy: str
    selection_reason: str
    fallback_used: bool
    estimated_cost: float
    candidates: list[RoutingCandidate]
    fallback_chain: list[str]
    rule_applied: str | None = None
    decided_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def _weighted_choice(weighted: list[tuple[RoutingCandidate, float]], rng: Any = random) -> RoutingCandidate:
    candidates = [c for c, _ in weighted]
    weights = [w for _, w in weighted]
    return rng.choices(candidates, weights=weights, k=1)[0]


class RoutingEngine:
    """Selects a provider/model for a request per a configurable policy.

    Builds a candidate list from the primary (catalog-resolved) provider plus same-tier
    equivalents on other enabled providers, so there's always a real fallback chain to
    execute against (Epic 4.3) - the caller is expected to try candidates in
    `fallback_chain` order and stop at the first success.
    """

    def __init__(
        self,
        model_registry: ModelRegistry,
        provider_registry: ProviderRegistry,
        health_monitor: ProviderHealthMonitor,
        config: RoutingConfig | None = None,
        rng: Any = random,
    ):
        self.model_registry = model_registry
        self.provider_registry = provider_registry
        self.health_monitor = health_monitor
        self.config = config or load_routing_config()
        self._rng = rng
        self._round_robin_counters: dict[str, int] = {}

    def _build_candidates(self, requested_model: str, required_capability: str | None = None) -> list[RoutingCandidate]:
        primary_provider, primary_upstream = self.model_registry.resolve_provider_model(requested_model)
        primary_def = self.model_registry.get_model(requested_model)

        require_vision = required_capability == "vision" or (
            required_capability is None and bool(primary_def and primary_def.supports_vision)
        )

        pool: list[tuple[str, str, Any, bool]] = []
        seen_providers = set()

        primary_matches_capability = not require_vision or not primary_def or primary_def.supports_vision
        if self.provider_registry.is_enabled(primary_provider) and primary_matches_capability:
            pool.append((primary_provider, primary_upstream, primary_def, True))
            seen_providers.add(primary_provider)

        for equivalent in self.model_registry.find_equivalents(requested_model, require_vision=require_vision):
            if equivalent.provider_name in seen_providers:
                continue
            if not self.provider_registry.is_enabled(equivalent.provider_name):
                continue
            pool.append((equivalent.provider_name, equivalent.provider_model_id, equivalent, False))
            seen_providers.add(equivalent.provider_name)

        candidates = []
        for provider_name, upstream_model, cost_def, is_primary in pool:
            metric = self.health_monitor.get_metrics(provider_name)
            estimated_cost = cost_def.estimate_cost(1000, 500) if cost_def else 0.0
            candidates.append(
                RoutingCandidate(
                    provider_name=provider_name,
                    upstream_model=upstream_model,
                    trust_score=metric.trust_score(),
                    latency_ms=metric.latency_ms or 0.0,
                    estimated_cost=estimated_cost,
                    is_primary=is_primary,
                    healthy=(metric.status != "offline" and not metric.is_rate_limited),
                )
            )
        return candidates

    def _resolve_named_provider_candidate(self, provider_name: str, requested_model: str) -> RoutingCandidate | None:
        """Build a candidate for a provider named explicitly by a routing rule action,
        even if it wouldn't normally qualify as a same-tier equivalent (an org rule is an
        explicit override, not a suggestion)."""
        provider_name = provider_name.lower()
        if not self.provider_registry.is_enabled(provider_name):
            return None

        provider_models = self.model_registry.list_models(provider_name=provider_name)
        if not provider_models:
            return None

        primary_def = self.model_registry.get_model(requested_model)
        chosen_def = next((m for m in provider_models if primary_def and m.tier == primary_def.tier), provider_models[0])

        metric = self.health_monitor.get_metrics(provider_name)
        return RoutingCandidate(
            provider_name=provider_name,
            upstream_model=chosen_def.provider_model_id,
            trust_score=metric.trust_score(),
            latency_ms=metric.latency_ms or 0.0,
            estimated_cost=chosen_def.estimate_cost(1000, 500),
            is_primary=False,
            healthy=(metric.status != "offline" and not metric.is_rate_limited),
        )

    def _apply_policy(
        self,
        policy: RoutingPolicy,
        requested_model: str,
        candidates: list[RoutingCandidate],
        preferred_provider: str | None,
    ) -> tuple[list[RoutingCandidate], str]:
        if policy == RoutingPolicy.LOWEST_LATENCY:
            ranked = sorted(candidates, key=lambda c: (c.latency_ms, not c.is_primary, -c.trust_score))
            top = ranked[0]
            return ranked, f"Lowest observed latency: {top.provider_name} averaging {top.latency_ms:.0f}ms"

        if policy == RoutingPolicy.LOWEST_COST:
            ranked = sorted(candidates, key=lambda c: (c.estimated_cost, not c.is_primary, -c.trust_score))
            top = ranked[0]
            return ranked, f"Lowest estimated cost: {top.provider_name} at ${top.estimated_cost:.4f} per request"

        if policy == RoutingPolicy.HIGHEST_AVAILABILITY:
            ranked = sorted(
                candidates,
                key=lambda c: (
                    -self.health_monitor.get_metrics(c.provider_name).success_rate,
                    not c.is_primary,
                    c.latency_ms,
                ),
            )
            top_rate = self.health_monitor.get_metrics(ranked[0].provider_name).success_rate
            return ranked, f"Highest recent success rate: {ranked[0].provider_name} at {top_rate:.1f}%"

        if policy == RoutingPolicy.USER_PREFERENCE:
            pref = (preferred_provider or self.config.preferred_provider or "").lower()
            if pref:
                preferred = [c for c in candidates if c.provider_name == pref]
                rest = sorted((c for c in candidates if c.provider_name != pref), key=lambda c: (not c.is_primary, -c.trust_score))
                if preferred:
                    return preferred + rest, f"Organization/project default provider: {pref}"
            ranked = sorted(candidates, key=lambda c: (not c.is_primary, -c.trust_score))
            return ranked, "No preferred provider configured or available; used highest trust score instead"

        if policy == RoutingPolicy.ROUND_ROBIN:
            key = requested_model.lower()
            turn = self._round_robin_counters.get(key, 0)
            offset = turn % len(candidates)
            ordered = candidates[offset:] + candidates[:offset]
            self._round_robin_counters[key] = turn + 1
            return ordered, f"Round-robin rotation (turn #{turn + 1} across {len(candidates)} candidates)"

        if policy == RoutingPolicy.WEIGHTED:
            weighted = [(c, self.config.weights.get(c.provider_name, 0.0)) for c in candidates]
            if not any(w > 0 for _, w in weighted):
                weighted = [(c, 1.0) for c, _ in weighted]
            chosen = _weighted_choice(weighted, rng=self._rng)
            weight_used = next(w for c, w in weighted if c is chosen)
            rest = sorted((c for c in candidates if c is not chosen), key=lambda c: (not c.is_primary, -c.trust_score))
            return [chosen] + rest, f"Weighted random selection: {chosen.provider_name} (weight {weight_used:g})"

        if policy == RoutingPolicy.CAPABILITY_BASED:
            ranked = sorted(candidates, key=lambda c: (not c.is_primary, -c.trust_score))
            return ranked, f"Highest-trust provider supporting the required capability: {ranked[0].provider_name}"

        ranked = sorted(candidates, key=lambda c: (not c.is_primary, -c.trust_score))
        return ranked, f"Selected by trust score ({ranked[0].trust_score})"

    def route(
        self,
        requested_model: str,
        policy: RoutingPolicy | None = None,
        required_capability: str | None = None,
        preferred_provider: str | None = None,
        rules: list[RuleSpec] | None = None,
    ) -> RoutingDecision:
        """Pick a provider/model for a request, returning the full ranked fallback chain
        and the reasoning behind the top pick.

        `rules` are an organization's routing rules (Epic 4.2), pre-fetched by the
        caller via apps.gateway.routing.rules.load_org_rules - evaluated BEFORE the
        policy ranking, since a rule is an explicit override ("always reject this",
        "always prefer ollama when the primary is down"), not one more ranking signal.
        """
        active_policy = policy or self.config.default_policy
        all_candidates = self._build_candidates(requested_model, required_capability)

        if not all_candidates:
            raise NoHealthyProviderError(f"No enabled provider is registered for model '{requested_model}'")

        healthy = [c for c in all_candidates if c.healthy]

        rule_outcome = None
        if rules:
            primary = next((c for c in all_candidates if c.is_primary), all_candidates[0])
            context = {
                "latency_ms": primary.latency_ms,
                "estimated_cost": primary.estimated_cost,
                "provider_status": "available" if primary.healthy else "unavailable",
            }
            rule_outcome = evaluate_rules(rules, context)

        if rule_outcome and rule_outcome.matched:
            if rule_outcome.action_type == RuleActionType.REJECT:
                raise RoutingRejectedError(f"Request rejected by routing rule '{rule_outcome.rule_name}' for model '{requested_model}'")

            if rule_outcome.action_provider:
                forced = next((c for c in healthy if c.provider_name == rule_outcome.action_provider.lower()), None)
                if not forced:
                    resolved = self._resolve_named_provider_candidate(rule_outcome.action_provider, requested_model)
                    if resolved and resolved.healthy:
                        all_candidates = all_candidates + [resolved]
                        healthy = healthy + [resolved]
                        forced = resolved

                if forced and forced.healthy:
                    rest = sorted(
                        (c for c in healthy if c.provider_name != forced.provider_name),
                        key=lambda c: (not c.is_primary, -c.trust_score),
                    )
                    ranked = [forced] + rest
                    selected = forced
                    reason = f"Routing rule '{rule_outcome.rule_name}' matched ({rule_outcome.action_type.value} -> {forced.provider_name})"
                    decision = RoutingDecision(
                        requested_model=requested_model,
                        selected_provider=selected.provider_name,
                        selected_upstream_model=selected.upstream_model,
                        routing_policy=active_policy.value,
                        selection_reason=reason,
                        fallback_used=not selected.is_primary,
                        estimated_cost=selected.estimated_cost,
                        candidates=all_candidates,
                        fallback_chain=[c.provider_name for c in ranked],
                        rule_applied=rule_outcome.rule_name,
                    )
                    logger.info(
                        f"Routed model='{requested_model}' -> provider='{selected.provider_name}' via rule='{rule_outcome.rule_name}'"
                    )
                    return decision
                logger.warning(
                    f"Rule '{rule_outcome.rule_name}' named provider "
                    f"'{rule_outcome.action_provider}' but it isn't enabled/healthy; falling back to policy ranking"
                )

        if not healthy:
            raise NoHealthyProviderError(f"No healthy provider is currently available for model '{requested_model}'")

        ranked, reason = self._apply_policy(active_policy, requested_model, healthy, preferred_provider)
        selected = ranked[0]

        decision = RoutingDecision(
            requested_model=requested_model,
            selected_provider=selected.provider_name,
            selected_upstream_model=selected.upstream_model,
            routing_policy=active_policy.value,
            selection_reason=reason,
            fallback_used=not selected.is_primary,
            estimated_cost=selected.estimated_cost,
            candidates=all_candidates,
            fallback_chain=[c.provider_name for c in ranked],
        )
        logger.info(
            f"Routed model='{requested_model}' -> provider='{selected.provider_name}' "
            f"policy='{active_policy.value}' fallback_used={decision.fallback_used}"
        )
        return decision
