import time
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from conftest import register_and_login
from fastapi.testclient import TestClient

from apps.gateway.db.models import EvalResult, EvalRun
from apps.gateway.db.retry import with_lock_retry
from apps.gateway.evaluation import execute_eval_run, score_response, validate_case_definition
from apps.gateway.evaluation.scorers import (
    ContainsScorer,
    ExactMatchScorer,
    StructuredOutputScorer,
    ToolCallSuccessScorer,
)
from apps.gateway.main import app

client = TestClient(app)


def _request_with_lock_retry(fn, *, attempts=5, initial_delay=0.05):
    """A fresh client.<verb>(...) call is a fully independent attempt through a new
    request-scoped session (unlike retrying session.commit() on one already-failed
    session, which SQLAlchemy refuses), so retrying the whole call is safe. Covers the
    same "fire-and-forget audit write from an earlier request is still settling on
    another connection when this request tries to write" gap that
    apps/gateway/db/retry.py's with_lock_retry covers for the app's own standalone
    writers - see test_delete_eval_suite.
    """
    delay = initial_delay
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as e:
            if "locked" not in str(e).lower() or attempt == attempts - 1:
                raise
            time.sleep(delay)
            delay *= 2


def _response(text: str, usage=None, tool_calls=None) -> dict:
    message = {"role": "assistant", "content": text}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {"choices": [{"message": message}], "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5}}


# ---------------------------------------------------------------------------
# Scorers (pure unit tests, no DB/network)
# ---------------------------------------------------------------------------


def test_exact_match_scorer_passes_on_identical_text():
    result = ExactMatchScorer().score(_response("Paris"), "Paris", None)
    assert result.passed is True
    assert result.score == 1.0


def test_exact_match_scorer_fails_on_different_text():
    result = ExactMatchScorer().score(_response("Lyon"), "Paris", None)
    assert result.passed is False
    assert result.score == 0.0


def test_exact_match_scorer_respects_case_sensitivity():
    resp = _response("PARIS")
    assert ExactMatchScorer().score(resp, "paris", None).passed is False
    assert ExactMatchScorer().score(resp, "paris", {"case_sensitive": False}).passed is True


def test_exact_match_scorer_strips_whitespace_by_default():
    result = ExactMatchScorer().score(_response("  Paris\n"), "Paris", None)
    assert result.passed is True


def test_exact_match_scorer_can_disable_whitespace_stripping():
    result = ExactMatchScorer().score(_response("  Paris\n"), "Paris", {"strip_whitespace": False})
    assert result.passed is False


def test_contains_scorer_all_mode_requires_every_substring():
    resp = _response("The capital of France is Paris.")
    passed = ContainsScorer().score(resp, ["capital", "Paris"], {"mode": "all"})
    assert passed.passed is True
    failed = ContainsScorer().score(resp, ["capital", "Berlin"], {"mode": "all"})
    assert failed.passed is False
    assert failed.details["missing"] == ["Berlin"]


def test_contains_scorer_any_mode_passes_with_one_match():
    resp = _response("The capital of France is Paris.")
    result = ContainsScorer().score(resp, ["Berlin", "Paris"], {"mode": "any"})
    assert result.passed is True


def test_contains_scorer_is_case_insensitive_by_default():
    result = ContainsScorer().score(_response("PARIS is lovely"), "paris", None)
    assert result.passed is True


def test_contains_scorer_accepts_single_string_expected_output():
    result = ContainsScorer().score(_response("hello world"), "world", None)
    assert result.passed is True
    assert result.score == 1.0


def test_structured_output_scorer_validates_against_schema():
    schema = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
    result = StructuredOutputScorer().score(_response('{"name": "Ada"}'), schema, None)
    assert result.passed is True


def test_structured_output_scorer_fails_on_invalid_json():
    schema = {"type": "object"}
    result = StructuredOutputScorer().score(_response("not json at all"), schema, None)
    assert result.passed is False
    assert "not valid JSON" in result.details["error"]


def test_structured_output_scorer_fails_on_schema_violation():
    schema = {"type": "object", "properties": {"age": {"type": "integer"}}, "required": ["age"]}
    result = StructuredOutputScorer().score(_response('{"age": "not a number"}'), schema, None)
    assert result.passed is False
    assert "error" in result.details


def test_tool_call_success_scorer_matches_name_only():
    tool_calls = [{"function": {"name": "get_weather", "arguments": '{"city": "Paris"}'}}]
    result = ToolCallSuccessScorer().score(_response("", tool_calls=tool_calls), {"tool_name": "get_weather"}, None)
    assert result.passed is True


def test_tool_call_success_scorer_matches_name_and_arguments_subset():
    tool_calls = [{"function": {"name": "get_weather", "arguments": '{"city": "Paris", "units": "metric"}'}}]
    expected = {"tool_name": "get_weather", "arguments": {"city": "Paris"}}
    result = ToolCallSuccessScorer().score(_response("", tool_calls=tool_calls), expected, None)
    assert result.passed is True


def test_tool_call_success_scorer_fails_when_no_matching_call():
    tool_calls = [{"function": {"name": "get_time", "arguments": "{}"}}]
    result = ToolCallSuccessScorer().score(_response("", tool_calls=tool_calls), {"tool_name": "get_weather"}, None)
    assert result.passed is False


def test_tool_call_success_scorer_fails_when_no_tool_calls_present():
    result = ToolCallSuccessScorer().score(_response("just text"), {"tool_name": "get_weather"}, None)
    assert result.passed is False


def test_score_response_raises_for_unknown_scorer_type():
    with pytest.raises(ValueError):
        score_response("not_a_real_scorer", _response("x"), "x", None)


@pytest.mark.parametrize(
    "scorer_type,expected_output",
    [
        ("contains", 123),
        ("structured_output", "not-a-schema-object"),
        ("structured_output", {"type": "not-a-real-type!!"}),
        ("tool_call_success", {"no_tool_name": True}),
        ("exact_match", None),
        ("bogus_scorer", "anything"),
    ],
)
def test_validate_case_definition_rejects_bad_shapes(scorer_type, expected_output):
    with pytest.raises(ValueError):
        validate_case_definition(scorer_type, expected_output)


def test_validate_case_definition_accepts_well_formed_cases():
    validate_case_definition("exact_match", "Paris")
    validate_case_definition("contains", ["a", "b"])
    validate_case_definition("structured_output", {"type": "object"})
    validate_case_definition("tool_call_success", {"tool_name": "get_weather"})


# ---------------------------------------------------------------------------
# Suite / case CRUD via the HTTP API
# ---------------------------------------------------------------------------


def _create_org():
    org_id, headers = register_and_login(client)
    return {"id": org_id}, headers


def _create_suite(org=None, headers=None, name="My Suite"):
    if org is None:
        org, headers = _create_org()
    suite = client.post("/eval/suites", json={"organization_id": org["id"], "name": name}, headers=headers).json()
    return org, headers, suite


def _create_case(suite_id, headers, **overrides):
    payload = {
        "name": "case 1",
        "messages": [{"role": "user", "content": "What is the capital of France?"}],
        "scorer_type": "exact_match",
        "expected_output": "Paris",
        **overrides,
    }
    resp = client.post(f"/eval/suites/{suite_id}/cases", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_and_get_eval_suite():
    org, headers, suite = _create_suite(name="Regression Suite")
    assert suite["name"] == "Regression Suite"
    assert suite["case_count"] == 0

    fetched = client.get(f"/eval/suites/{suite['id']}", headers=headers).json()
    assert fetched["id"] == suite["id"]


def test_list_eval_suites_scoped_to_organization():
    org_a, headers_a = _create_org()
    org_b, headers_b = _create_org()
    client.post("/eval/suites", json={"organization_id": org_a["id"], "name": "Suite A"}, headers=headers_a)
    client.post("/eval/suites", json={"organization_id": org_b["id"], "name": "Suite B"}, headers=headers_b)

    listed = client.get("/eval/suites", params={"organization_id": org_a["id"]}, headers=headers_a).json()
    assert len(listed) == 1
    assert listed[0]["name"] == "Suite A"


def test_update_eval_suite():
    _, headers, suite = _create_suite()
    resp = client.patch(f"/eval/suites/{suite['id']}", json={"description": "updated desc"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["description"] == "updated desc"


def test_delete_eval_suite():
    _, headers, suite = _create_suite()
    # create_eval_suite fires an audit write via fire_and_forget that can still be
    # settling on another connection - see _request_with_lock_retry.
    resp = _request_with_lock_retry(lambda: client.delete(f"/eval/suites/{suite['id']}", headers=headers))
    assert resp.status_code == 200
    assert client.get(f"/eval/suites/{suite['id']}", headers=headers).status_code == 404


def test_get_eval_suite_404_for_unknown_id():
    _, headers = _create_org()
    assert client.get(f"/eval/suites/{uuid.uuid4()}", headers=headers).status_code == 404


def test_create_eval_case_under_suite_updates_case_count():
    _, headers, suite = _create_suite()
    case = _create_case(suite["id"], headers)
    assert case["scorer_type"] == "exact_match"

    fetched_suite = client.get(f"/eval/suites/{suite['id']}", headers=headers).json()
    assert fetched_suite["case_count"] == 1

    cases = client.get(f"/eval/suites/{suite['id']}/cases", headers=headers).json()
    assert len(cases) == 1
    assert cases[0]["id"] == case["id"]


def test_create_eval_case_rejects_unknown_scorer_type():
    _, headers, suite = _create_suite()
    resp = client.post(
        f"/eval/suites/{suite['id']}/cases",
        json={
            "name": "bad case",
            "messages": [{"role": "user", "content": "hi"}],
            "scorer_type": "not_a_scorer",
            "expected_output": "x",
        },
        headers=headers,
    )
    assert resp.status_code == 400


def test_create_eval_case_rejects_invalid_json_schema_for_structured_output():
    _, headers, suite = _create_suite()
    resp = client.post(
        f"/eval/suites/{suite['id']}/cases",
        json={
            "name": "bad schema",
            "messages": [{"role": "user", "content": "hi"}],
            "scorer_type": "structured_output",
            "expected_output": {"type": "definitely-not-a-json-schema-type"},
        },
        headers=headers,
    )
    assert resp.status_code == 400


def test_create_eval_case_rejects_message_missing_role_or_content():
    _, headers, suite = _create_suite()
    resp = client.post(
        f"/eval/suites/{suite['id']}/cases",
        json={
            "name": "bad message",
            "messages": [{"role": "user"}],
            "scorer_type": "exact_match",
            "expected_output": "x",
        },
        headers=headers,
    )
    assert resp.status_code == 422


def test_update_eval_case_revalidates_new_scorer_shape():
    _, headers, suite = _create_suite()
    case = _create_case(suite["id"], headers)

    ok = client.patch(f"/eval/cases/{case['id']}", json={"name": "renamed"}, headers=headers)
    assert ok.status_code == 200
    assert ok.json()["name"] == "renamed"

    bad = client.patch(f"/eval/cases/{case['id']}", json={"scorer_type": "tool_call_success"}, headers=headers)
    assert bad.status_code == 400  # expected_output is still "Paris", not a valid tool_call_success shape


def test_delete_eval_case():
    _, headers, suite = _create_suite()
    case = _create_case(suite["id"], headers)
    resp = client.delete(f"/eval/cases/{case['id']}", headers=headers)
    assert resp.status_code == 200
    assert client.get(f"/eval/cases/{case['id']}", headers=headers).status_code == 404


def test_create_run_requires_at_least_one_case():
    _, headers, suite = _create_suite()
    resp = client.post("/eval/runs", json={"suite_id": suite["id"], "model": "gpt-4o"}, headers=headers)
    assert resp.status_code == 400


def test_create_run_404s_for_unknown_suite():
    _, headers = _create_org()
    resp = client.post("/eval/runs", json={"suite_id": str(uuid.uuid4()), "model": "gpt-4o"}, headers=headers)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Run creation wiring (endpoint schedules execution; doesn't wait for it)
# ---------------------------------------------------------------------------


def test_create_run_endpoint_schedules_execution_and_returns_pending():
    _, headers, suite = _create_suite()
    _create_case(suite["id"], headers)

    with patch("apps.gateway.api.evaluation.execute_eval_run", new_callable=AsyncMock) as mock_execute:
        resp = client.post("/eval/runs", json={"suite_id": suite["id"], "model": "gpt-4o"}, headers=headers)

    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "pending"
    assert body["total_cases"] == 1
    assert body["suite_name"] == suite["name"]
    mock_execute.assert_called_once()
    assert str(mock_execute.call_args[0][0]) == body["id"]


# ---------------------------------------------------------------------------
# Run execution (calls execute_eval_run directly + awaits it, per this repo's
# established pattern for testing fire-and-forget logic deterministically -
# TestClient's blocking portal can cancel a task scheduled mid-request before it
# finishes, so real execution is verified by awaiting the coroutine directly
# rather than by racing a POST /eval/runs call).
# ---------------------------------------------------------------------------


async def _make_run(db_session, suite_id, organization_id, suite_name, model="gpt-4o", total_cases=1) -> EvalRun:
    run = EvalRun(
        id=uuid.uuid4(),
        suite_id=uuid.UUID(suite_id),
        suite_name=suite_name,
        organization_id=uuid.UUID(organization_id),
        model=model,
        status="pending",
        total_cases=total_cases,
    )
    db_session.add(run)
    await with_lock_retry(db_session.commit)
    return run


@pytest.mark.asyncio
async def test_execute_eval_run_scores_each_case_and_completes(db_session):
    org, headers, suite = _create_suite()
    case_pass = _create_case(suite["id"], headers, name="capital", expected_output="Paris")
    case_fail = _create_case(suite["id"], headers, name="math", messages=[{"role": "user", "content": "2+2?"}], expected_output="4")

    run = await _make_run(db_session, suite["id"], org["id"], suite["name"], total_cases=2)

    with patch(
        "plugins.providers.openai.plugin.OpenAIProviderPlugin.chat",
        new_callable=AsyncMock,
        side_effect=[_response("Paris"), _response("not four")],
    ):
        await execute_eval_run(run.id)

    finished = client.get(f"/eval/runs/{run.id}", headers=headers).json()
    assert finished["status"] == "completed"
    assert finished["total_cases"] == 2
    assert finished["passed_cases"] == 1
    assert finished["failed_cases"] == 1
    assert finished["avg_latency_ms"] is not None
    assert finished["completed_at"] is not None

    results = {r["case_name"]: r for r in client.get(f"/eval/runs/{run.id}/results", headers=headers).json()}
    assert results["capital"]["passed"] is True
    assert results["math"]["passed"] is False
    assert results["math"]["actual_output"] == "not four"
    assert results["capital"]["case_id"] == case_pass["id"]
    assert results["math"]["case_id"] == case_fail["id"]


@pytest.mark.asyncio
async def test_execute_eval_run_records_cost_from_real_usage(db_session):
    org, headers, suite = _create_suite()
    _create_case(suite["id"], headers)
    run = await _make_run(db_session, suite["id"], org["id"], suite["name"])

    usage = {"prompt_tokens": 1000, "completion_tokens": 1000}
    with patch(
        "plugins.providers.openai.plugin.OpenAIProviderPlugin.chat",
        new_callable=AsyncMock,
        return_value=_response("Paris", usage=usage),
    ):
        await execute_eval_run(run.id)

    finished = client.get(f"/eval/runs/{run.id}", headers=headers).json()
    # gpt-4o catalog pricing: $0.0025/1k input + $0.01/1k output -> 1k+1k tokens = 0.0125
    assert finished["total_cost_usd"] == pytest.approx(0.0125, rel=1e-6)


@pytest.mark.asyncio
async def test_execute_eval_run_marks_failed_when_org_rule_rejects_model(db_session):
    """execute_eval_run loads the run's organization's routing rules (same as live
    /v1/chat/completions traffic) before executing any case - an org that has
    configured a REJECT rule should have that honored by eval runs too, not just
    real customer requests."""
    org, headers, suite = _create_suite()
    _create_case(suite["id"], headers)
    reject_resp = client.post(
        "/routing-rules",
        json={
            "organization_id": org["id"],
            "name": "block-all",
            "condition_expression": "estimated_cost > 0.001",
            "action_type": "reject",
        },
        headers=headers,
    )
    assert reject_resp.status_code == 201, reject_resp.text

    run = await _make_run(db_session, suite["id"], org["id"], suite["name"], model="gpt-4o")
    await execute_eval_run(run.id)

    finished = client.get(f"/eval/runs/{run.id}", headers=headers).json()
    assert finished["status"] == "failed"
    assert "not routable" in finished["error_message"]


@pytest.mark.asyncio
async def test_execute_eval_run_records_per_case_error_when_provider_raises(db_session):
    """gpt-4o's fallback chain in this default test config is [openai, gemini] (the
    only other enabled provider with a flagship-tier equivalent) - both must fail for
    the case itself to error out, otherwise Epic 4.4 failover correctly serves the
    request from gemini instead, exactly as it would in production."""
    org, headers, suite = _create_suite()
    _create_case(suite["id"], headers)
    run = await _make_run(db_session, suite["id"], org["id"], suite["name"])

    with (
        patch(
            "plugins.providers.openai.plugin.OpenAIProviderPlugin.chat",
            new_callable=AsyncMock,
            side_effect=RuntimeError("openai upstream exploded"),
        ),
        patch(
            "plugins.providers.gemini.plugin.GeminiProviderPlugin.chat",
            new_callable=AsyncMock,
            side_effect=RuntimeError("gemini upstream exploded"),
        ),
    ):
        await execute_eval_run(run.id)

    finished = client.get(f"/eval/runs/{run.id}", headers=headers).json()
    assert finished["status"] == "completed"
    assert finished["failed_cases"] == 1

    results = client.get(f"/eval/runs/{run.id}/results", headers=headers).json()
    assert results[0]["passed"] is False
    assert results[0]["error_message"]


# ---------------------------------------------------------------------------
# Results / run history listing (direct DB writes -> HTTP reads)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_eval_results_for_run(db_session):
    org, headers, suite = _create_suite()
    run = await _make_run(db_session, suite["id"], org["id"], suite["name"])
    db_session.add(EvalResult(id=uuid.uuid4(), run_id=run.id, case_id=None, case_name="orphaned case", passed=True, score=1.0))
    await with_lock_retry(db_session.commit)

    results = client.get(f"/eval/runs/{run.id}/results", headers=headers).json()
    assert len(results) == 1
    assert results[0]["case_name"] == "orphaned case"
    assert results[0]["case_id"] is None


@pytest.mark.asyncio
async def test_list_eval_runs_for_suite_orders_most_recent_first(db_session):
    org, headers, suite = _create_suite()
    older = await _make_run(db_session, suite["id"], org["id"], suite["name"], model="gpt-4o-mini")
    newer = await _make_run(db_session, suite["id"], org["id"], suite["name"], model="gpt-4o")

    runs = client.get(f"/eval/suites/{suite['id']}/runs", headers=headers).json()
    ids = [r["id"] for r in runs]
    assert ids.index(str(newer.id)) < ids.index(str(older.id))


def test_get_run_404_for_unknown_id():
    _, headers = _create_org()
    assert client.get(f"/eval/runs/{uuid.uuid4()}", headers=headers).status_code == 404


def test_delete_run():
    _, headers, suite = _create_suite()
    _create_case(suite["id"], headers)
    with patch("apps.gateway.api.evaluation.execute_eval_run", new_callable=AsyncMock):
        run = client.post("/eval/runs", json={"suite_id": suite["id"], "model": "gpt-4o"}, headers=headers).json()

    # create_eval_run also fires an audit write via fire_and_forget - see
    # _request_with_lock_retry.
    resp = _request_with_lock_retry(lambda: client.delete(f"/eval/runs/{run['id']}", headers=headers))
    assert resp.status_code == 200
    assert client.get(f"/eval/runs/{run['id']}", headers=headers).status_code == 404
