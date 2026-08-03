import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.gateway.analytics import RequestTimeline, record_request, record_time_machine_entry
from apps.gateway.auth import KeyPermission, RequestAuthContext, resolve_auth_or_401
from apps.gateway.cache import compute_cache_key
from apps.gateway.db.models import CachePolicy
from apps.gateway.db.session import get_db_session
from apps.gateway.policy import PolicyViolation, enforce_policies
from apps.gateway.providers.instance import (
    cache_manager,
    health_monitor,
    model_registry,
    provider_registry,
    rate_limiter,
    routing_engine,
)
from apps.gateway.ratelimit import enforce_rate_limits
from apps.gateway.routing import (
    NoHealthyProviderError,
    RoutingDecision,
    RoutingPolicy,
    RoutingRejectedError,
    load_org_rules,
)
from apps.gateway.utils import fire_and_forget
from packages.plugin_sdk import ChatRequest, EmbeddingRequest
from packages.shared.logging.logger import get_logger
from packages.shared.streaming import safe_sse_stream_generator

logger = get_logger("openai_v1")

router = APIRouter(prefix="/v1", tags=["OpenAI Compatible API"])


class ChatCompletionMessage(BaseModel):
    role: str = Field(description="Role of the message author ('system', 'user', 'assistant', 'tool')")
    content: str | list[Any] | None = Field(default="", description="Content of the message")
    name: str | None = None


class OpenAIRequest(BaseModel):
    model: str = Field(description="Model identifier")
    messages: list[ChatCompletionMessage] | None = None
    input: str | list[str] | None = None
    temperature: float | None = 0.7
    top_p: float | None = 1.0
    max_tokens: int | None = None
    stream: bool | None = False
    stop: str | list[str] | None = None
    tools: list[dict[str, Any]] | None = Field(
        default=None,
        description="OpenAI-format tool definitions. Included in the cache key (Epic 5.1); "
        "not yet forwarded to providers - functional tool-calling is a separate, larger effort.",
    )


@router.get("/models")
async def list_v1_models(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """List available models in OpenAI API format, including dynamically discovered local Ollama models."""
    client_ip = request.client.host if request.client else None
    await resolve_auth_or_401(db, authorization, client_ip, KeyPermission.MODELS_READ)

    models_list = model_registry.list_models()
    formatted_models = [
        {
            "id": m.model_id,
            "object": "model",
            "created": 1600000000,
            "owned_by": m.provider_name,
            "permission": [],
            "root": m.provider_model_id,
            "parent": None,
        }
        for m in models_list
    ]

    # Dynamically query Ollama for locally installed pulled models
    ollama_provider = provider_registry.get_provider("ollama")
    if ollama_provider:
        try:
            ollama_models = await ollama_provider.models()
            existing_ids = {m["id"] for m in formatted_models}
            for o_model in ollama_models.models:
                if o_model not in existing_ids:
                    formatted_models.append(
                        {
                            "id": o_model,
                            "object": "model",
                            "created": int(time.time()),
                            "owned_by": "ollama",
                            "permission": [],
                            "root": o_model,
                            "parent": None,
                        }
                    )
        except Exception as e:
            logger.debug(f"Skipping local Ollama model discovery: {e}")

    return {
        "object": "list",
        "data": formatted_models,
    }


def _reassemble_streaming_response(chunks: list[str], model: str) -> dict[str, Any]:
    """Rebuild an OpenAI-shaped non-streaming response from cached SSE chunks, so a
    streaming-cached entry can also serve a later non-streaming request for the same
    (provider, model, messages, ...) - not just a raw chunk replay."""
    import json as _json

    content_parts: list[str] = []
    finish_reason = "stop"
    for chunk in chunks:
        if not chunk.startswith("data: "):
            continue
        payload = chunk[len("data: ") :].strip()
        if payload == "[DONE]":
            continue
        try:
            data = _json.loads(payload)
        except ValueError:
            continue
        for choice in data.get("choices", []):
            delta = choice.get("delta", {})
            if delta.get("content"):
                content_parts.append(delta["content"])
            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]

    return {
        "id": f"chatcmpl-cached-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "".join(content_parts)}, "finish_reason": finish_reason}],
    }


def _filter_permitted_candidates(attempt_order: list[tuple], auth_context: RequestAuthContext | None) -> list[tuple]:
    """Epic 5.3: a key scoped to specific providers/models only ever gets routed to -
    and failed over across - candidates within that scope, never silently served by a
    provider/model the key isn't allowed to use."""
    if not auth_context or (not auth_context.allowed_providers and not auth_context.allowed_models):
        return attempt_order
    allowed_providers = auth_context.allowed_providers
    allowed_models = auth_context.allowed_models
    return [
        (name, model)
        for name, model in attempt_order
        if (not allowed_providers or name in allowed_providers) and (not allowed_models or model in allowed_models)
    ]


def _detects_vision_request(messages: list[ChatCompletionMessage]) -> bool:
    """Deterministic capability detection (RFC-0005: rules remain available even when
    AI-assisted classification is off) - true if any message contains OpenAI-style
    multimodal image_url content parts."""
    for message in messages:
        if not isinstance(message.content, list):
            continue
        for part in message.content:
            if isinstance(part, dict) and part.get("type") == "image_url":
                return True
    return False


def _parse_routing_policy_header(header_value: str | None) -> RoutingPolicy | None:
    if not header_value:
        return None
    try:
        return RoutingPolicy(header_value)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown routing policy '{header_value}'") from None


async def _try_serve_from_cache(
    db: AsyncSession,
    cache_policy: CachePolicy,
    attempt_order: list[tuple],
    message_dicts: list[dict[str, Any]],
    req: OpenAIRequest,
    decision: RoutingDecision,
    timeline: RequestTimeline,
    request_id: str,
    resolved_organization_id: str | None,
    resolved_project_id: str | None,
    debug_header_value: str | None,
) -> Any | None:
    """Checks the cache for the primary candidate and, on a usable hit, records the
    request and returns the response to send - the caller returns this as-is when
    it's not None. Returns None on a miss (or when caching is disabled), meaning the
    caller should fall through to actually calling a provider.

    A cached streaming response can serve a non-streaming re-request (just return the
    body), but not the reverse - synthesizing a plausible stream from a cached
    non-streaming blob isn't attempted, so that case is treated as a miss too.
    """
    if not cache_policy.enabled:
        return None

    primary_provider, primary_upstream_model = attempt_order[0]
    primary_cache_key = compute_cache_key(primary_provider, primary_upstream_model, message_dicts, req.temperature, req.top_p, req.tools)
    cached = await cache_manager.get(primary_cache_key, db)
    if not cached or (req.stream and not cached.is_streaming):
        return None

    timeline.mark("cache_hit")
    await record_request(
        request_id=request_id,
        requested_model=req.model,
        status="success",
        timeline=timeline,
        organization_id=resolved_organization_id,
        project_id=resolved_project_id,
        selected_provider=primary_provider,
        routing_policy=decision.routing_policy,
        fallback_used=decision.fallback_used,
        rule_applied=decision.rule_applied,
        estimated_cost=0.0,
        cache_hit=True,
    )
    if req.stream and cached.stream_chunks:

        async def _replay_cached_stream(chunks=cached.stream_chunks):
            for chunk in chunks:
                yield chunk

        stream_headers = {"X-Setu-Routing-Debug": debug_header_value} if debug_header_value else None
        return StreamingResponse(_replay_cached_stream(), media_type="text/event-stream", headers=stream_headers)
    return cached.response_body


@router.post("/chat/completions")
async def chat_completions(
    req: OpenAIRequest,
    response: Response,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    authorization: str | None = Header(default=None),
    x_setu_debug: str | None = Header(default=None, alias="X-Setu-Debug"),
    x_setu_routing_policy: str | None = Header(default=None, alias="X-Setu-Routing-Policy"),
    x_setu_organization_id: str | None = Header(default=None, alias="X-Setu-Organization-Id"),
    x_setu_time_machine: str | None = Header(default=None, alias="X-Setu-Time-Machine"),
) -> Any:
    """OpenAI-compatible Chat Completion endpoint supporting streaming & multi-provider routing.

    Authentication is real but not mandatory: a valid `Authorization: Bearer sk_setu_...`
    key (see apps/gateway/api/keys.py) resolves the calling project/organization and is
    the preferred, secure source for org routing rules (Epic 4.2). A key that's
    presented but doesn't resolve (revoked/expired/unknown) is rejected outright rather
    than silently treated as anonymous. X-Setu-Organization-Id remains a fallback for
    unauthenticated dev/playground use - making auth mandatory on this endpoint is a
    bigger, separate decision that would break the current playground/quickstart/test
    flows, which all call it unauthenticated today.
    """
    if not req.messages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Field 'messages' is required for chat completions",
        )

    timeline = RequestTimeline()

    client_ip = request.client.host if request.client else None
    auth_context = await resolve_auth_or_401(db, authorization, client_ip, KeyPermission.CHAT)
    # Flush resolve_api_key's last_used_at update now rather than leaving it pending
    # on `db` for the rest of the request: record_request/cache_manager.set_standalone/
    # record_time_machine_entry all open their OWN session to write concurrently (see
    # their docstrings), and a still-open write on `db` at the same time can make a
    # single-writer database (e.g. SQLite in tests) briefly reject those writes.
    await db.commit()
    resolved_organization_id = auth_context.organization_id if auth_context else x_setu_organization_id
    policy_override = _parse_routing_policy_header(x_setu_routing_policy)
    required_capability = "vision" if _detects_vision_request(req.messages) else None

    org_rules = None
    if resolved_organization_id:
        try:
            org_rules = await load_org_rules(db, uuid.UUID(resolved_organization_id))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid organization id: '{resolved_organization_id}'",
            ) from None

    request_id = str(uuid.uuid4())
    if resolved_organization_id:
        try:
            await enforce_policies(
                db,
                organization_id=resolved_organization_id,
                requested_model=req.model,
                messages=[m.model_dump() for m in req.messages],
                model_registry=model_registry,
            )
        except PolicyViolation as e:
            timeline.mark("policy_blocked")
            await record_request(
                request_id=request_id,
                requested_model=req.model,
                status="error",
                timeline=timeline,
                organization_id=resolved_organization_id,
                project_id=auth_context.project_id if auth_context else None,
                error_message=str(e),
            )
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e

    try:
        decision = routing_engine.route(req.model, policy=policy_override, required_capability=required_capability, rules=org_rules)
        request_id = decision.request_id
    except (NoHealthyProviderError, RoutingRejectedError) as e:
        timeline.mark("routing_failed")
        await record_request(
            request_id=request_id,
            requested_model=req.model,
            status="error",
            timeline=timeline,
            organization_id=resolved_organization_id,
            project_id=auth_context.project_id if auth_context else None,
            routing_policy=policy_override.value if policy_override else None,
            error_message=str(e),
        )
        if isinstance(e, NoHealthyProviderError):
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)) from e
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e

    timeline.mark("routed")

    candidate_upstream_models = {c.provider_name: c.upstream_model for c in decision.candidates}
    attempt_order = _filter_permitted_candidates(
        [(name, candidate_upstream_models[name]) for name in decision.fallback_chain], auth_context
    )
    if not attempt_order:
        timeline.mark("routing_failed")
        await record_request(
            request_id=request_id,
            requested_model=req.model,
            status="error",
            timeline=timeline,
            organization_id=resolved_organization_id,
            project_id=auth_context.project_id if auth_context else None,
            routing_policy=decision.routing_policy,
            error_message="No routing candidate is within this API key's allowed providers/models",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This API key's provider/model restrictions exclude every available routing candidate",
        )

    try:
        await enforce_rate_limits(
            db,
            rate_limiter,
            endpoint="/v1/chat/completions",
            organization_id=resolved_organization_id,
            project_id=auth_context.project_id if auth_context else None,
            provider_name=attempt_order[0][0],
            auth_context=auth_context,
        )
    except HTTPException as e:
        if e.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            timeline.mark("rate_limited")
            await record_request(
                request_id=request_id,
                requested_model=req.model,
                status="error",
                timeline=timeline,
                organization_id=resolved_organization_id,
                project_id=auth_context.project_id if auth_context else None,
                routing_policy=decision.routing_policy,
                error_message=e.detail,
            )
        raise

    debug_header_value: str | None = None
    if (x_setu_debug or "").strip().lower() == "true":
        debug_header_value = decision.model_dump_json()
        response.headers["X-Setu-Routing-Debug"] = debug_header_value

    time_machine_requested = (x_setu_time_machine or "").strip().lower() == "true"
    resolved_project_id = auth_context.project_id if auth_context else None
    message_dicts = [m.model_dump(exclude_none=True) for m in req.messages]
    cache_policy = await cache_manager.get_policy(resolved_project_id, db)

    cached_response = await _try_serve_from_cache(
        db,
        cache_policy,
        attempt_order,
        message_dicts,
        req,
        decision,
        timeline,
        request_id,
        resolved_organization_id,
        resolved_project_id,
        debug_header_value,
    )
    if cached_response is not None:
        return cached_response

    last_error: Exception | None = None
    for attempt_provider_name, attempt_upstream_model in attempt_order:
        provider = provider_registry.get_provider(attempt_provider_name)
        if not provider:
            continue

        chat_req = ChatRequest(
            model=attempt_upstream_model,
            messages=[m.model_dump(exclude_none=True) for m in req.messages],
            temperature=req.temperature,
            top_p=req.top_p,
            max_tokens=req.max_tokens,
            stream=req.stream,
            stop=req.stop,
        )

        start_time = time.time()
        try:
            res = await provider.chat(chat_req)

            if req.stream:
                # Epic 4.4: retry/failover is only safe until the first byte reaches the
                # client. `res` here is an un-started async generator (provider.chat()
                # just returns stream_chat(request) for stream=True without running any
                # of its body), so peeking one chunk still lets a connection failure be
                # treated like any other failed attempt and fail over normally. Once
                # that first chunk exists, we've committed - the wrapped generator below
                # is what safe_sse_stream_generator falls back to on any *later* error,
                # not another provider attempt (that would duplicate/corrupt output the
                # client may have already received).
                first_chunk = await res.__anext__()
                latency_ms = (time.time() - start_time) * 1000
                health_monitor.record_request_result(provider.provider_name, success=True, latency_ms=latency_ms)
                timeline.mark("streaming_started")

                async def _prepend_first_chunk(
                    first=first_chunk,
                    rest=res,
                    provider=provider,
                    attempt_upstream_model=attempt_upstream_model,
                    start_time=start_time,
                ):
                    collected = [first]
                    yield first
                    async for chunk in rest:
                        collected.append(chunk)
                        yield chunk
                    if cache_policy.enabled:
                        # Fire-and-forget: caching must never add latency to the
                        # response, and by this point the stream is already fully
                        # delivered to the client either way.
                        write_key = compute_cache_key(
                            provider.provider_name,
                            attempt_upstream_model,
                            message_dicts,
                            req.temperature,
                            req.top_p,
                            req.tools,
                        )
                        fire_and_forget(
                            cache_manager.set_standalone(
                                cache_key=write_key,
                                response_body=_reassemble_streaming_response(collected, attempt_upstream_model),
                                provider=provider.provider_name,
                                model=attempt_upstream_model,
                                project_id=resolved_project_id,
                                ttl_seconds=cache_policy.ttl_seconds,
                                is_streaming=True,
                                stream_chunks=collected,
                            )
                        )
                    if time_machine_requested:
                        fire_and_forget(
                            record_time_machine_entry(
                                request_id=request_id,
                                requested_model=req.model,
                                provider=provider.provider_name,
                                upstream_model=attempt_upstream_model,
                                request_messages=message_dicts,
                                request_params={
                                    "temperature": req.temperature,
                                    "top_p": req.top_p,
                                    "max_tokens": req.max_tokens,
                                    "stop": req.stop,
                                },
                                response_body=_reassemble_streaming_response(collected, attempt_upstream_model),
                                latency_ms=(time.time() - start_time) * 1000,
                                estimated_cost=decision.estimated_cost,
                                organization_id=resolved_organization_id,
                                project_id=resolved_project_id,
                            )
                        )

                safe_stream = safe_sse_stream_generator(
                    _prepend_first_chunk(),
                    timeout_seconds=30.0,
                    provider_name=provider.provider_name,
                )
                stream_headers = {"X-Setu-Routing-Debug": debug_header_value} if debug_header_value else None
                timeline.mark("completed")
                # Token usage isn't knowable until the stream finishes, which happens
                # after this handler returns - recorded without it rather than blocking
                # the response on end-of-stream instrumentation.
                await record_request(
                    request_id=request_id,
                    requested_model=req.model,
                    status="success",
                    timeline=timeline,
                    organization_id=resolved_organization_id,
                    project_id=resolved_project_id,
                    selected_provider=provider.provider_name,
                    routing_policy=decision.routing_policy,
                    fallback_used=(attempt_provider_name != decision.selected_provider or decision.fallback_used),
                    rule_applied=decision.rule_applied,
                    estimated_cost=decision.estimated_cost,
                )
                return StreamingResponse(safe_stream, media_type="text/event-stream", headers=stream_headers)

            latency_ms = (time.time() - start_time) * 1000
            health_monitor.record_request_result(provider.provider_name, success=True, latency_ms=latency_ms)
            timeline.mark("completed")
            await record_request(
                request_id=request_id,
                requested_model=req.model,
                status="success",
                timeline=timeline,
                organization_id=resolved_organization_id,
                project_id=resolved_project_id,
                selected_provider=provider.provider_name,
                routing_policy=decision.routing_policy,
                fallback_used=(attempt_provider_name != decision.selected_provider or decision.fallback_used),
                rule_applied=decision.rule_applied,
                usage=res.get("usage") if isinstance(res, dict) else None,
                estimated_cost=decision.estimated_cost,
            )
            if cache_policy.enabled and isinstance(res, dict):
                write_key = compute_cache_key(
                    provider.provider_name, attempt_upstream_model, message_dicts, req.temperature, req.top_p, req.tools
                )
                await cache_manager.set(
                    write_key,
                    res,
                    provider.provider_name,
                    attempt_upstream_model,
                    db,
                    project_id=resolved_project_id,
                    ttl_seconds=cache_policy.ttl_seconds,
                )
                # Same reasoning as the earlier commit after auth resolution: this
                # write on `db` must be flushed before record_time_machine_entry below
                # opens its own concurrent session.
                await db.commit()
            if time_machine_requested and isinstance(res, dict):
                await record_time_machine_entry(
                    request_id=request_id,
                    requested_model=req.model,
                    provider=provider.provider_name,
                    upstream_model=attempt_upstream_model,
                    request_messages=message_dicts,
                    request_params={
                        "temperature": req.temperature,
                        "top_p": req.top_p,
                        "max_tokens": req.max_tokens,
                        "stop": req.stop,
                    },
                    response_body=res,
                    latency_ms=latency_ms,
                    estimated_cost=decision.estimated_cost,
                    organization_id=resolved_organization_id,
                    project_id=resolved_project_id,
                )
            return res
        except StopAsyncIteration:
            # Provider produced an empty stream - not a failure worth failing over for.
            latency_ms = (time.time() - start_time) * 1000
            health_monitor.record_request_result(provider.provider_name, success=True, latency_ms=latency_ms)
            timeline.mark("completed")

            async def _empty_stream():
                return
                yield  # pragma: no cover - makes this an async generator

            stream_headers = {"X-Setu-Routing-Debug": debug_header_value} if debug_header_value else None
            await record_request(
                request_id=request_id,
                requested_model=req.model,
                status="success",
                timeline=timeline,
                organization_id=resolved_organization_id,
                project_id=resolved_project_id,
                selected_provider=provider.provider_name,
                routing_policy=decision.routing_policy,
                fallback_used=(attempt_provider_name != decision.selected_provider or decision.fallback_used),
                rule_applied=decision.rule_applied,
                estimated_cost=decision.estimated_cost,
            )
            return StreamingResponse(
                safe_sse_stream_generator(_empty_stream(), provider_name=provider.provider_name),
                media_type="text/event-stream",
                headers=stream_headers,
            )
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            health_monitor.record_request_result(provider.provider_name, success=False, latency_ms=latency_ms)
            last_error = e
            logger.warning(f"Provider '{attempt_provider_name}' failed, trying next candidate: {e}")
            continue

    timeline.mark("all_providers_failed")
    await record_request(
        request_id=request_id,
        requested_model=req.model,
        status="error",
        timeline=timeline,
        organization_id=resolved_organization_id,
        project_id=resolved_project_id,
        routing_policy=decision.routing_policy,
        rule_applied=decision.rule_applied,
        error_message=f"All providers failed: {last_error}",
    )
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"All providers failed for model '{req.model}': {last_error}",
    )


@router.post("/embeddings")
async def embeddings(
    req: OpenAIRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    authorization: str | None = Header(default=None),
) -> Any:
    """OpenAI-compatible Vector Embedding endpoint."""
    if not req.input:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Field 'input' is required for embeddings",
        )

    client_ip = request.client.host if request.client else None
    auth_context = await resolve_auth_or_401(db, authorization, client_ip, KeyPermission.EMBEDDINGS)

    provider_name, upstream_model = model_registry.resolve_provider_model(req.model)
    provider = provider_registry.get_provider(provider_name)

    if not provider:
        provider = provider_registry.get_provider("openai") or provider_registry.get_provider("ollama")

    if not provider:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"No active embedding provider available for model '{req.model}'",
        )

    if not _filter_permitted_candidates([(provider.provider_name, upstream_model)], auth_context):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This API key's provider/model restrictions exclude this embedding request",
        )

    await enforce_rate_limits(
        db,
        rate_limiter,
        endpoint="/v1/embeddings",
        organization_id=auth_context.organization_id if auth_context else None,
        project_id=auth_context.project_id if auth_context else None,
        provider_name=provider.provider_name,
        auth_context=auth_context,
    )

    embed_req = EmbeddingRequest(model=upstream_model, input=req.input)
    start_time = time.time()
    try:
        res = await provider.embeddings(embed_req)
        latency_ms = (time.time() - start_time) * 1000
        health_monitor.record_request_result(provider.provider_name, success=True, latency_ms=latency_ms)
        return res
    except Exception as e:
        latency_ms = (time.time() - start_time) * 1000
        health_monitor.record_request_result(provider.provider_name, success=False, latency_ms=latency_ms)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Embedding request failed: {str(e)}",
        ) from e
