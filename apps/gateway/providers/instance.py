from apps.gateway.models.catalog import ModelRegistry
from apps.gateway.providers.health_monitor import ProviderHealthMonitor
from apps.gateway.providers.registry import ProviderCapabilities, ProviderRegistry
from apps.gateway.routing.engine import RoutingEngine
from packages.shared.config.providers_config import load_providers_config
from plugins.providers import (
    AnthropicProviderPlugin,
    GeminiProviderPlugin,
    GroqProviderPlugin,
    OllamaProviderPlugin,
    OpenAIProviderPlugin,
)

# Global singleton registries for gateway
provider_registry = ProviderRegistry()
model_registry = ModelRegistry()
health_monitor = ProviderHealthMonitor(provider_registry)

# Load provider configuration settings from YAML/environment
prov_config = load_providers_config()

# Register default provider adapters with configured enablement state
provider_registry.register_provider(
    OpenAIProviderPlugin(),
    capabilities=ProviderCapabilities(chat=True, embeddings=True, image=True, audio=True, vision=True, tools=True),
    enabled=prov_config.providers.get("openai", {}).enabled if hasattr(prov_config.providers.get("openai"), "enabled") else True,
)
provider_registry.register_provider(
    OllamaProviderPlugin(),
    capabilities=ProviderCapabilities(chat=True, embeddings=True, tools=True),
    enabled=prov_config.providers.get("ollama", {}).enabled if hasattr(prov_config.providers.get("ollama"), "enabled") else True,
)
provider_registry.register_provider(
    AnthropicProviderPlugin(),
    capabilities=ProviderCapabilities(chat=True, vision=True, tools=True),
    enabled=prov_config.providers.get("anthropic", {}).enabled if hasattr(prov_config.providers.get("anthropic"), "enabled") else False,
)
provider_registry.register_provider(
    GeminiProviderPlugin(),
    capabilities=ProviderCapabilities(chat=True, embeddings=True, image=True, audio=True, vision=True, tools=True),
    enabled=prov_config.providers.get("gemini", {}).enabled if hasattr(prov_config.providers.get("gemini"), "enabled") else True,
)
provider_registry.register_provider(
    GroqProviderPlugin(),
    capabilities=ProviderCapabilities(chat=True, audio=True, tools=True),
    enabled=prov_config.providers.get("groq", {}).enabled if hasattr(prov_config.providers.get("groq"), "enabled") else True,
)

# Intelligent router (Epic 4.1) - built on the same registries above, so it always sees
# the current enablement/health state.
routing_engine = RoutingEngine(model_registry, provider_registry, health_monitor)
