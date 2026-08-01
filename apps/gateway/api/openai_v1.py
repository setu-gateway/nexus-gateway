import time
from typing import Any, Dict, List, Optional, Union
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.gateway.analytics import RequestTimeline, record_request
from apps.gateway.auth import resolve_api_key
from apps.gateway.db.session import get_db_session
from apps.gateway.providers.instance import health_monitor, model_registry, provider_registry, routing_engine
from apps.gateway.routing import NoHealthyProviderError, RoutingPolicy, RoutingRejectedError, load_org_rules
from packages.plugin_sdk import ChatRequest, EmbeddingRequest
from packages.shared.logging.logger import get_logger
from packages.shared.streaming import safe_sse_stream_generator

logger = get_logger("openai_v1")

router = APIRouter(prefix="/v1", tags=["OpenAI Compatible API"])


class ChatCompletionMessage(BaseModel):
    role: str = Field(description="Role of the message author ('system', 'user', 'assistant', 'tool')")
    content: Optional[Union[str, List[Any]]] = Field(default="", description="Content of the message")
    name: Optional[str] = None


class OpenAIRequest(BaseModel):
    model: str = Field(description="Model identifier")
    messages: Optional[List[ChatCompletionMessage]] = None
    input: Optional[Union[str, List[str]]] = None
    temperature: Optional[float] = 0.7
    top_p: Optional[float] = 1.0
    max_tokens: Optional[int] = None
    stream: Optional[bool] = False
    stop: Optional[Union[str, List[str]]] = None


@router.get("/models")
async def list_v1_models() -> Dict[str, Any]:
    """List available models in OpenAI API format, including dynamically discovered local Ollama models."""
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
        except Exception:
            pass

    return {
        "object": "list",
        "data": formatted_models,
    }


def _detects_vision_request(messages: List[ChatCompletionMessage]) -> bool:
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


@router.post("/chat/completions")
async def chat_completions(
    req: OpenAIRequest,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
    authorization: Optional[str] = Header(default=None),
    x_setu_debug: Optional[str] = Header(default=None, alias="X-Setu-Debug"),
    x_setu_routing_policy: Optional[str] = Header(default=None, alias="X-Setu-Routing-Policy"),
    x_setu_organization_id: Optional[str] = Header(default=None, alias="X-Setu-Organization-Id"),
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

    auth_context = await resolve_api_key(db, authorization)
    if authorization and authorization.startswith("Bearer ") and auth_context is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key is invalid, revoked, or expired",
        )
    resolved_organization_id = auth_context.organization_id if auth_context else x_setu_organization_id

    policy_override: Optional[RoutingPolicy] = None
    if x_setu_routing_policy:
        try:
            policy_override = RoutingPolicy(x_setu_routing_policy)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown routing policy '{x_setu_routing_policy}'",
            )

    required_capability = "vision" if _detects_vision_request(req.messages) else None

    org_rules = None
    if resolved_organization_id:
        try:
            org_rules = await load_org_rules(db, uuid.UUID(resolved_organization_id))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid organization id: '{resolved_organization_id}'",
            )

    request_id = str(uuid.uuid4())
    try:
        decision = routing_engine.route(
            req.model, policy=policy_override, required_capability=required_capability, rules=org_rules
        )
        request_id = decision.request_id
    except (NoHealthyProviderError, RoutingRejectedError) as e:
        timeline.mark("routing_failed")
        await record_request(
            request_id=request_id,
            requested_model=req.model,
            status="error",
            timeline=timeline,
            organization_id=resolved_organization_id,
            routing_policy=policy_override.value if policy_override else None,
            error_message=str(e),
        )
        if isinstance(e, NoHealthyProviderError):
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))

    timeline.mark("routed")

    debug_header_value: Optional[str] = None
    if (x_setu_debug or "").strip().lower() == "true":
        debug_header_value = decision.model_dump_json()
        response.headers["X-Setu-Routing-Debug"] = debug_header_value

    candidate_upstream_models = {c.provider_name: c.upstream_model for c in decision.candidates}
    attempt_order = [(name, candidate_upstream_models[name]) for name in decision.fallback_chain]

    last_error: Optional[Exception] = None
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

                async def _prepend_first_chunk(first=first_chunk, rest=res):
                    yield first
                    async for chunk in rest:
                        yield chunk

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
                selected_provider=provider.provider_name,
                routing_policy=decision.routing_policy,
                fallback_used=(attempt_provider_name != decision.selected_provider or decision.fallback_used),
                rule_applied=decision.rule_applied,
                usage=res.get("usage") if isinstance(res, dict) else None,
                estimated_cost=decision.estimated_cost,
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
        routing_policy=decision.routing_policy,
        rule_applied=decision.rule_applied,
        error_message=f"All providers failed: {last_error}",
    )
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"All providers failed for model '{req.model}': {last_error}",
    )


@router.post("/embeddings")
async def embeddings(req: OpenAIRequest) -> Any:
    """OpenAI-compatible Vector Embedding endpoint."""
    if not req.input:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Field 'input' is required for embeddings",
        )

    provider_name, upstream_model = model_registry.resolve_provider_model(req.model)
    provider = provider_registry.get_provider(provider_name)

    if not provider:
        provider = provider_registry.get_provider("openai") or provider_registry.get_provider("ollama")

    if not provider:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"No active embedding provider available for model '{req.model}'",
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
        )
