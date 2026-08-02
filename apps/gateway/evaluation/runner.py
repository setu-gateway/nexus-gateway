import time
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from apps.gateway.db import session as db_session_module
from apps.gateway.db.models import EvalCase, EvalResult, EvalRun
from apps.gateway.db.retry import with_lock_retry
from apps.gateway.evaluation.scorers import score_response
from apps.gateway.providers.instance import model_registry, provider_registry, routing_engine
from apps.gateway.routing import NoHealthyProviderError, RoutingRejectedError, RuleSpec, load_org_rules
from packages.plugin_sdk import ChatRequest
from packages.shared.logging.logger import get_logger

logger = get_logger("eval_runner")

# Eval scorers (exact match, contains, structured output, tool call) look for a
# specific correct answer, not creative variation - a low fixed temperature keeps runs
# reproducible run-to-run instead of flaking on sampling noise.
_EVAL_TEMPERATURE = 0.0


async def _execute_case(
    model: str, messages: list[dict[str, Any]], rules: list[RuleSpec] | None = None
) -> tuple[dict[str, Any] | None, float | None, float | None, str | None]:
    """Runs one case's messages through the same routing + provider fallback chain
    live traffic uses (apps/gateway/api/openai_v1.py's chat_completions), including the
    run's organization's routing rules - deliberately skipping only the cache and rate
    limiter, since an eval needs a fresh real response every time and run execution is
    an internal/admin action, not billable customer traffic.

    Returns (response, latency_ms, cost_usd, error_message); exactly one of
    response/error_message is set on return.
    """
    try:
        decision = routing_engine.route(model, rules=rules)
    except (NoHealthyProviderError, RoutingRejectedError) as e:
        return None, None, None, str(e)

    candidate_upstream_models = {c.provider_name: c.upstream_model for c in decision.candidates}
    attempt_order = [(name, candidate_upstream_models[name]) for name in decision.fallback_chain]
    model_def = model_registry.get_model(model)

    last_error: Exception | None = None
    for provider_name, upstream_model in attempt_order:
        provider = provider_registry.get_provider(provider_name)
        if not provider:
            continue

        chat_req = ChatRequest(model=upstream_model, messages=messages, temperature=_EVAL_TEMPERATURE)
        start_time = time.time()
        try:
            res = await provider.chat(chat_req)
        except Exception as e:
            last_error = e
            continue

        latency_ms = (time.time() - start_time) * 1000
        usage = res.get("usage") if isinstance(res, dict) else None
        cost_usd = None
        if model_def and isinstance(usage, dict):
            cost_usd = model_def.estimate_cost(usage.get("prompt_tokens") or 0, usage.get("completion_tokens") or 0)
        return res, latency_ms, cost_usd, None

    return None, None, None, str(last_error) if last_error else "No healthy provider available for this model"


async def _load_run_and_cases(
    run_id: uuid.UUID,
) -> tuple[str, uuid.UUID, list[dict[str, Any]]] | None:
    async def _load() -> tuple[str, uuid.UUID, list[dict[str, Any]]] | None:
        async with db_session_module.async_session_factory() as session:
            run = await session.get(EvalRun, run_id)
            if not run:
                return None
            result = await session.execute(select(EvalCase).where(EvalCase.suite_id == run.suite_id).order_by(EvalCase.created_at))
            cases = list(result.scalars().all())
            # Detach the plain data this function needs from the session before it
            # closes, rather than handing back ORM instances bound to a dead session.
            return (
                run.model,
                run.organization_id,
                [
                    {
                        "id": c.id,
                        "name": c.name,
                        "messages": c.messages,
                        "scorer_type": c.scorer_type,
                        "expected_output": c.expected_output,
                        "scorer_config": c.scorer_config,
                    }
                    for c in cases
                ],
            )

    return await with_lock_retry(_load)


async def _load_rules(organization_id: uuid.UUID) -> list[RuleSpec]:
    async def _load() -> list[RuleSpec]:
        async with db_session_module.async_session_factory() as session:
            return await load_org_rules(session, organization_id)

    return await with_lock_retry(_load)


async def _mark_run_failed(run_id: uuid.UUID, error_message: str) -> None:
    async def _write() -> None:
        async with db_session_module.async_session_factory() as session:
            run = await session.get(EvalRun, run_id)
            if not run:
                return
            run.status = "failed"
            run.error_message = error_message
            run.completed_at = datetime.now(timezone.utc)
            await session.commit()

    await with_lock_retry(_write)


async def execute_eval_run(run_id: uuid.UUID) -> None:
    """Executes every case in an EvalRun's suite against the run's model, scoring and
    persisting each result as it completes. Runs as a fire-and-forget background task
    kicked off by POST /eval/runs; never raises - any failure is recorded on the run
    row itself (status="failed") rather than as an unhandled exception in a detached
    task.
    """
    try:
        loaded = await _load_run_and_cases(run_id)
        if loaded is None:
            logger.warning(f"eval run {run_id} disappeared before execution started")
            return
        model, organization_id, cases = loaded

        if not cases:
            await _mark_run_failed(run_id, "Suite has no cases to run")
            return

        rules = await _load_rules(organization_id)

        # Fail fast with one clear error if the model can't be routed at all, rather
        # than repeating the same routing failure once per case below.
        try:
            routing_engine.route(model, rules=rules)
        except (NoHealthyProviderError, RoutingRejectedError) as e:
            await _mark_run_failed(run_id, f"Model '{model}' is not routable: {e}")
            return

        async def _mark_running() -> None:
            async with db_session_module.async_session_factory() as session:
                run = await session.get(EvalRun, run_id)
                if run:
                    run.status = "running"
                    await session.commit()

        await with_lock_retry(_mark_running)

        passed_count = 0
        latencies: list[float] = []
        total_cost = 0.0
        any_cost = False

        for case in cases:
            response, latency_ms, cost_usd, error = await _execute_case(model, case["messages"], rules=rules)

            if error is not None:
                passed, score, details, actual_output = False, 0.0, {}, None
            else:
                if response is None:
                    raise AssertionError("_execute_case guarantees response is set when error is None")
                result = score_response(case["scorer_type"], response, case["expected_output"], case["scorer_config"])
                passed, score, details = result.passed, result.score, result.details
                actual_output = details.get("actual") if isinstance(details.get("actual"), str) else None

            if passed:
                passed_count += 1
            if latency_ms is not None:
                latencies.append(latency_ms)
            if cost_usd is not None:
                total_cost += cost_usd
                any_cost = True

            async def _write_result(
                case=case,
                passed=passed,
                score=score,
                actual_output=actual_output,
                latency_ms=latency_ms,
                cost_usd=cost_usd,
                error=error,
                details=details,
            ) -> None:
                async with db_session_module.async_session_factory() as session:
                    session.add(
                        EvalResult(
                            id=uuid.uuid4(),
                            run_id=run_id,
                            case_id=case["id"],
                            case_name=case["name"],
                            passed=passed,
                            score=score,
                            actual_output=actual_output,
                            latency_ms=latency_ms,
                            cost_usd=cost_usd,
                            error_message=error,
                            details=details or None,
                        )
                    )
                    await session.commit()

            await with_lock_retry(_write_result)

        async def _finalize() -> None:
            async with db_session_module.async_session_factory() as session:
                run = await session.get(EvalRun, run_id)
                if not run:
                    return
                run.status = "completed"
                run.total_cases = len(cases)
                run.passed_cases = passed_count
                run.failed_cases = len(cases) - passed_count
                run.avg_latency_ms = (sum(latencies) / len(latencies)) if latencies else None
                run.total_cost_usd = total_cost if any_cost else None
                run.completed_at = datetime.now(timezone.utc)
                await session.commit()

        await with_lock_retry(_finalize)

    except Exception as e:
        logger.error(f"eval run {run_id} failed: {e}")
        try:
            await _mark_run_failed(run_id, str(e))
        except Exception as mark_failed_error:
            logger.error(f"eval run {run_id} could not even be marked failed: {mark_failed_error}")
