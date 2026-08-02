from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from apps.gateway.providers.instance import model_registry, provider_registry
from packages.shared.logging.logger import get_logger

logger = get_logger("models_api")

router = APIRouter(prefix="/models", tags=["Unified Model Registry"])


class UnifiedModelResponse(BaseModel):
    id: str = Field(description="Unified model identifier used by clients")
    provider: str = Field(description="Associated LLM provider name")
    display_name: str = Field(description="Human-readable display name")
    context_window: int = Field(description="Maximum context token limit")
    capabilities: dict[str, bool] = Field(description="Capability flags")


@router.get("", response_model=list[UnifiedModelResponse])
async def list_unified_models() -> list[UnifiedModelResponse]:
    """List all available models in unified format across all active providers."""
    models_list = model_registry.list_models()
    res: list[UnifiedModelResponse] = [
        UnifiedModelResponse(
            id=m.model_id,
            provider=m.provider_name,
            display_name=m.display_name,
            context_window=m.context_window,
            capabilities={
                "tools": m.supports_tools,
                "streaming": m.supports_streaming,
                "vision": m.supports_vision,
                "embeddings": m.supports_embeddings,
            },
        )
        for m in models_list
    ]

    # Include locally discovered Ollama models
    ollama_p = provider_registry.get_provider("ollama")
    if ollama_p:
        try:
            o_models = await ollama_p.models()
            existing_ids = {m.id for m in res}
            for name in o_models.models:
                if name not in existing_ids:
                    res.append(
                        UnifiedModelResponse(
                            id=name,
                            provider="ollama",
                            display_name=f"Ollama {name}",
                            context_window=128000,
                            capabilities={
                                "tools": True,
                                "streaming": True,
                                "vision": False,
                                "embeddings": False,
                            },
                        )
                    )
        except Exception as e:
            logger.debug(f"Skipping local Ollama model discovery: {e}")

    return res


@router.get("/{id}", response_model=UnifiedModelResponse)
async def get_unified_model(id: str) -> UnifiedModelResponse:
    """Retrieve metadata for a specific model by unified ID."""
    key = id.lower()
    model = model_registry.get_model(key)

    if model:
        return UnifiedModelResponse(
            id=model.model_id,
            provider=model.provider_name,
            display_name=model.display_name,
            context_window=model.context_window,
            capabilities={
                "tools": model.supports_tools,
                "streaming": model.supports_streaming,
                "vision": model.supports_vision,
                "embeddings": model.supports_embeddings,
            },
        )

    # Check dynamically discovered models
    all_models = await list_unified_models()
    found = next((m for m in all_models if m.id.lower() == key), None)

    if not found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model '{id}' not found in unified catalog",
        )

    return found
