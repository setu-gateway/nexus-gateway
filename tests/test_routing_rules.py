import random
import uuid

from fastapi.testclient import TestClient
import pytest

from apps.gateway.main import app
from apps.gateway.models.catalog import ModelRegistry
from apps.gateway.providers.health_monitor import ProviderHealthMonitor
from apps.gateway.providers.registry import ProviderRegistry
from apps.gateway.routing.engine import NoHealthyProviderError, RoutingEngine, RoutingRejectedError
from apps.gateway.routing.rules import (
    RuleActionType,
    RuleConditionError,
    RuleSpec,
    evaluate_rules,
    parse_condition,
)

client = TestClient(app)


# --- condition parsing -------------------------------------------------------------


def test_parse_condition_latency_with_ms_suffix():
    condition = parse_condition("latency > 500ms")
    assert condition.field == "latency_ms"
    assert condition.operator == ">"
    assert condition.value == 500.0


def test_parse_condition_latency_with_seconds_normalizes_to_ms():
    condition = parse_condition("latency > 2s")
    assert condition.value == 2000.0


def test_parse_condition_provider_status():
    condition = parse_condition("provider == unavailable")
    assert condition.field == "provider_status"
    assert condition.operator == "=="
    assert condition.value == "unavailable"


def test_parse_condition_cost():
    condition = parse_condition("estimated_cost > 0.01")
    assert condition.field == "estimated_cost"
    assert condition.value == 0.01


def test_parse_condition_rejects_garbage_without_eval():
    with pytest.raises(RuleConditionError):
        parse_condition("__import__('os').system('echo pwned')")


def test_parse_condition_rejects_unknown_field():
    with pytest.raises(RuleConditionError):
        parse_condition("moon_phase == full")


# --- rule evaluation ----------------------------------------------------------------


def test_evaluate_rules_matches_highest_priority_first():
    rules = [
        RuleSpec(name="low", condition_expression="latency > 100ms", action_type=RuleActionType.FALLBACK,
                  action_provider="groq", priority=200),
        RuleSpec(name="high", condition_expression="latency > 100ms", action_type=RuleActionType.USE,
                  action_provider="ollama", priority=10),
    ]
    outcome = evaluate_rules(rules, {"latency_ms": 500, "estimated_cost": 0.001, "provider_status": "available"})
    assert outcome.matched is True
    assert outcome.rule_name == "high"


def test_evaluate_rules_skips_disabled_rules():
    rules = [
        RuleSpec(name="disabled", condition_expression="latency > 100ms", action_type=RuleActionType.REJECT,
                  enabled=False, priority=1),
    ]
    outcome = evaluate_rules(rules, {"latency_ms": 999})
    assert outcome.matched is False


def test_evaluate_rules_no_match_returns_unmatched():
    rules = [RuleSpec(name="r", condition_expression="latency > 999999ms", action_type=RuleActionType.REJECT)]
    outcome = evaluate_rules(rules, {"latency_ms": 10})
    assert outcome.matched is False


def test_evaluate_rules_skips_unparseable_rule_without_crashing():
    rules = [
        RuleSpec(name="broken", condition_expression="not a valid condition!!", action_type=RuleActionType.REJECT,
                  priority=1),
        RuleSpec(name="ok", condition_expression="latency > 100ms", action_type=RuleActionType.REJECT, priority=2),
    ]
    outcome = evaluate_rules(rules, {"latency_ms": 500})
    assert outcome.matched is True
    assert outcome.rule_name == "ok"


# --- routing engine integration ------------------------------------------------------


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


def test_rule_reject_action_raises():
    engine = _make_engine()
    rules = [RuleSpec(name="cap", condition_expression="estimated_cost > 0.001", action_type=RuleActionType.REJECT)]
    with pytest.raises(RoutingRejectedError):
        engine.route("gpt-4o", rules=rules)


def test_rule_use_action_forces_named_provider_outside_normal_tier():
    engine = _make_engine()
    # groq's catalog model is "fast" tier, not a normal equivalent of flagship gpt-4o -
    # a rule naming it explicitly should still be honored.
    rules = [
        RuleSpec(name="force-groq", condition_expression="latency > -1ms", action_type=RuleActionType.USE,
                  action_provider="groq")
    ]
    decision = engine.route("gpt-4o", rules=rules)
    assert decision.selected_provider == "groq"
    assert decision.rule_applied == "force-groq"


def test_rule_fallback_action_used_when_primary_unavailable():
    engine = _make_engine()
    for _ in range(10):
        engine.health_monitor.record_request_result("openai", success=False, latency_ms=100)

    rules = [
        RuleSpec(name="reroute-on-outage", condition_expression="provider == unavailable",
                  action_type=RuleActionType.FALLBACK, action_provider="ollama")
    ]
    decision = engine.route("gpt-4o", rules=rules)
    assert decision.selected_provider == "ollama"


def test_rule_that_does_not_match_falls_through_to_normal_policy():
    engine = _make_engine()
    rules = [
        RuleSpec(name="never-matches", condition_expression="latency > 999999ms", action_type=RuleActionType.REJECT)
    ]
    decision = engine.route("gpt-4o", rules=rules)
    assert decision.selected_provider == "openai"
    assert decision.rule_applied is None


def test_rule_naming_disabled_provider_degrades_to_policy_ranking():
    engine = _make_engine()
    engine.provider_registry.disable_provider("groq")
    rules = [
        RuleSpec(name="force-disabled", condition_expression="latency > -1ms", action_type=RuleActionType.USE,
                  action_provider="groq")
    ]
    # Should not raise - falls back to normal ranking since groq isn't available.
    decision = engine.route("gpt-4o", rules=rules)
    assert decision.selected_provider != "groq"


# --- CRUD API -------------------------------------------------------------------------


def test_routing_rules_crud_lifecycle():
    org_id = str(uuid.uuid4())

    create_resp = client.post(
        "/routing-rules",
        json={
            "organization_id": org_id,
            "name": "Reroute on slow OpenAI",
            "condition_expression": "latency > 500ms",
            "action_type": "fallback",
            "action_provider": "groq",
            "priority": 10,
        },
    )
    assert create_resp.status_code == 201
    rule = create_resp.json()
    assert rule["organization_id"] == org_id
    rule_id = rule["id"]

    list_resp = client.get("/routing-rules", params={"organization_id": org_id})
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    get_resp = client.get(f"/routing-rules/{rule_id}")
    assert get_resp.status_code == 200

    patch_resp = client.patch(f"/routing-rules/{rule_id}", json={"enabled": False, "priority": 5})
    assert patch_resp.status_code == 200
    assert patch_resp.json()["enabled"] is False
    assert patch_resp.json()["priority"] == 5

    delete_resp = client.delete(f"/routing-rules/{rule_id}")
    assert delete_resp.status_code == 200

    assert client.get(f"/routing-rules/{rule_id}").status_code == 404


def test_create_routing_rule_rejects_invalid_condition_syntax():
    resp = client.post(
        "/routing-rules",
        json={
            "organization_id": str(uuid.uuid4()),
            "name": "bad",
            "condition_expression": "this is not valid",
            "action_type": "reject",
        },
    )
    assert resp.status_code == 400


def test_create_routing_rule_requires_provider_for_fallback_action():
    resp = client.post(
        "/routing-rules",
        json={
            "organization_id": str(uuid.uuid4()),
            "name": "missing-provider",
            "condition_expression": "latency > 500ms",
            "action_type": "fallback",
        },
    )
    assert resp.status_code == 400
