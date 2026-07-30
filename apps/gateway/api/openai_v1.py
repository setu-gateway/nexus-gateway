import time
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from apps.gateway.providers.instance import health_monitor, model_registry, provider_registry
from packages.plugin_sdk import ChatRequest, EmbeddingRequest
from packages.shared.streaming import safe_sse_stream_generator

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
    """List available models in OpenAI API format."""
    models_list = model_registry.list_models()
    return {
        "object": "list",
        "data": [
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
        ],
    }


@router.post("/chat/completions")
async def chat_completions(req: OpenAIRequest) -> Any:
    """OpenAI-compatible Chat Completion endpoint supporting streaming & multi-provider routing."""
    if not req.messages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Field 'messages' is required for chat completions",
        )

    provider_name, upstream_model = model_registry.resolve_provider_model(req.model)
    provider = provider_registry.get_provider(provider_name)

    if not provider:
        healthiest = health_monitor.get_healthiest_provider(["openai", "ollama", "groq", "gemini"])
        provider = provider_registry.get_provider(healthiest) if healthiest else None

    if not provider:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"No active provider available for model '{req.model}'",
        )

    chat_req = ChatRequest(
        model=upstream_model,
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
        latency_ms = (time.time() - start_time) * 1000
        health_monitor.record_request_result(provider.provider_name, success=True, latency_ms=latency_ms)

        if req.stream:
            safe_stream = safe_sse_stream_generator(
                res,
                timeout_seconds=30.0,
                provider_name=provider.provider_name,
            )
            return StreamingResponse(safe_stream, media_type="text/event-stream")
        return res
    except Exception as e:
        latency_ms = (time.time() - start_time) * 1000
        health_monitor.record_request_result(provider.provider_name, success=False, latency_ms=latency_ms)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Provider request failed: {str(e)}",
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
