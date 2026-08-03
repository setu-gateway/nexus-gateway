from pydantic import BaseModel, Field

from packages.shared.logging.logger import get_logger

logger = get_logger("model_registry")


class ModelDefinition(BaseModel):
    """Unified Model Definition for Setu Gateway catalog."""

    model_id: str = Field(description="Unified model identifier used by clients")
    display_name: str = Field(description="Human readable display name")
    provider_name: str = Field(description="Associated LLM provider name (e.g. 'openai', 'anthropic')")
    provider_model_id: str = Field(description="Actual upstream model ID expected by provider API")
    context_window: int = Field(default=128000, description="Token context window size")
    supports_tools: bool = Field(default=True, description="Supports function calling / tool use")
    supports_streaming: bool = Field(default=True, description="Supports SSE token streaming")
    supports_vision: bool = Field(default=False, description="Supports image / multimodal input")
    supports_embeddings: bool = Field(default=False, description="Is a vector embedding model")
    tier: str = Field(
        default="fast",
        description="Rough capability class used for cross-provider fallback equivalence: 'flagship', 'fast', or 'embedding'",
    )
    input_cost_per_1k: float = Field(
        default=0.0, ge=0.0, description="Approximate USD cost per 1K input tokens (0 for self-hosted/free models)"
    )
    output_cost_per_1k: float = Field(
        default=0.0, ge=0.0, description="Approximate USD cost per 1K output tokens (0 for self-hosted/free models)"
    )

    def estimate_cost(self, input_tokens: float, output_tokens: float = 0) -> float:
        """Estimate request cost in USD from token counts. Pricing is illustrative and
        should be kept in sync with each provider's published pricing page."""
        return round(
            (input_tokens / 1000.0) * self.input_cost_per_1k + (output_tokens / 1000.0) * self.output_cost_per_1k,
            6,
        )


class ModelRegistry:
    """Unified Model Catalog and Translation Registry for Setu Gateway."""

    def __init__(self):
        self._catalog: dict[str, ModelDefinition] = {}
        self._load_default_catalog()

    def _load_default_catalog(self) -> None:
        """Seed registry with built-in model definitions across providers."""
        defaults = [
            # OpenAI Models
            ModelDefinition(
                model_id="gpt-4o",
                display_name="GPT-4o",
                provider_name="openai",
                provider_model_id="gpt-4o",
                context_window=128000,
                supports_tools=True,
                supports_streaming=True,
                supports_vision=True,
                tier="flagship",
                input_cost_per_1k=0.0025,
                output_cost_per_1k=0.01,
            ),
            ModelDefinition(
                model_id="gpt-4o-mini",
                display_name="GPT-4o Mini",
                provider_name="openai",
                provider_model_id="gpt-4o-mini",
                context_window=128000,
                supports_tools=True,
                supports_streaming=True,
                supports_vision=True,
                tier="fast",
                input_cost_per_1k=0.00015,
                output_cost_per_1k=0.0006,
            ),
            ModelDefinition(
                model_id="text-embedding-3-small",
                display_name="OpenAI Text Embedding 3 Small",
                provider_name="openai",
                provider_model_id="text-embedding-3-small",
                context_window=8191,
                supports_tools=False,
                supports_streaming=False,
                supports_embeddings=True,
                tier="embedding",
                input_cost_per_1k=0.00002,
            ),
            # Anthropic Models
            ModelDefinition(
                model_id="claude-3-5-sonnet",
                display_name="Claude 3.5 Sonnet",
                provider_name="anthropic",
                provider_model_id="claude-3-5-sonnet-20241022",
                context_window=200000,
                supports_tools=True,
                supports_streaming=True,
                supports_vision=True,
                tier="flagship",
                input_cost_per_1k=0.003,
                output_cost_per_1k=0.015,
            ),
            ModelDefinition(
                model_id="claude-3-5-haiku",
                display_name="Claude 3.5 Haiku",
                provider_name="anthropic",
                provider_model_id="claude-3-5-haiku-20241022",
                context_window=200000,
                supports_tools=True,
                supports_streaming=True,
                tier="fast",
                input_cost_per_1k=0.0008,
                output_cost_per_1k=0.004,
            ),
            # Ollama Models
            ModelDefinition(
                model_id="llama3",
                display_name="Llama 3 (Local)",
                provider_name="ollama",
                provider_model_id="llama3.2",
                context_window=128000,
                supports_tools=True,
                supports_streaming=True,
                tier="fast",
                input_cost_per_1k=0.0,
                output_cost_per_1k=0.0,
            ),
            ModelDefinition(
                model_id="mistral",
                display_name="Mistral 7B (Local)",
                provider_name="ollama",
                provider_model_id="mistral",
                context_window=32768,
                supports_tools=True,
                supports_streaming=True,
                tier="fast",
                input_cost_per_1k=0.0,
                output_cost_per_1k=0.0,
            ),
            # Gemini Models
            ModelDefinition(
                model_id="gemini-1.5-pro",
                display_name="Gemini 1.5 Pro",
                provider_name="gemini",
                provider_model_id="gemini-1.5-pro",
                context_window=1000000,
                supports_tools=True,
                supports_streaming=True,
                supports_vision=True,
                tier="flagship",
                input_cost_per_1k=0.00125,
                output_cost_per_1k=0.005,
            ),
            ModelDefinition(
                model_id="gemini-1.5-flash",
                display_name="Gemini 1.5 Flash",
                provider_name="gemini",
                provider_model_id="gemini-1.5-flash",
                context_window=1000000,
                supports_tools=True,
                supports_streaming=True,
                supports_vision=True,
                tier="fast",
                input_cost_per_1k=0.000075,
                output_cost_per_1k=0.0003,
            ),
            # Groq Models
            ModelDefinition(
                model_id="groq-llama-3.3",
                display_name="Llama 3.3 70B (Groq LPU)",
                provider_name="groq",
                provider_model_id="llama-3.3-70b-versatile",
                context_window=128000,
                supports_tools=True,
                supports_streaming=True,
                tier="fast",
                input_cost_per_1k=0.00059,
                output_cost_per_1k=0.00079,
            ),
        ]

        for m in defaults:
            self.register_model(m)

    def register_model(self, model: ModelDefinition) -> None:
        """Register or update a model definition in the catalog."""
        key = model.model_id.lower()
        self._catalog[key] = model
        logger.info(f"Registered model '{model.display_name}' ({key}) -> provider '{model.provider_name}'")

    def get_model(self, model_id: str) -> ModelDefinition | None:
        """Get model definition by unified model ID."""
        return self._catalog.get(model_id.lower())

    def resolve_provider_model(self, unified_model_id: str) -> tuple[str, str]:
        """Resolve a unified model ID into (provider_name, provider_model_id)."""
        key = unified_model_id.lower()
        model_def = self._catalog.get(key)
        if model_def:
            return model_def.provider_name, model_def.provider_model_id

        # Fallback: Treat raw string as OpenAI provider model if unlisted
        return "openai", unified_model_id

    def list_models(self, provider_name: str | None = None) -> list[ModelDefinition]:
        """List models in the catalog, optionally filtered by provider."""
        models = list(self._catalog.values())
        if provider_name:
            target_prov = provider_name.lower()
            models = [m for m in models if m.provider_name == target_prov]
        return models

    def find_equivalents(self, model_id: str, require_vision: bool | None = None) -> list[ModelDefinition]:
        """Find same-tier models from OTHER providers, for cross-provider routing fallback.

        Used when the primary provider for a requested model is unavailable: the router
        needs a real upstream model to call on a different provider, not just a healthy
        provider name. Matching on tier (and, when relevant, vision support) keeps a
        fallback roughly equivalent in capability rather than swapping a flagship request
        for an unrelated cheap/local model.
        """
        primary = self.get_model(model_id)
        if not primary:
            return []

        candidates = [
            m
            for m in self._catalog.values()
            if m.provider_name != primary.provider_name and m.tier == primary.tier and m.supports_embeddings == primary.supports_embeddings
        ]
        if require_vision or (require_vision is None and primary.supports_vision):
            candidates = [m for m in candidates if m.supports_vision]

        return candidates
