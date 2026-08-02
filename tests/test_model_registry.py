from apps.gateway.models import ModelDefinition, ModelRegistry


def test_model_registry_initialization():
    registry = ModelRegistry()
    models = registry.list_models()

    assert len(models) >= 10
    model_ids = [m.model_id for m in models]
    assert "gpt-4o" in model_ids
    assert "claude-3-5-sonnet" in model_ids
    assert "llama3" in model_ids
    assert "gemini-1.5-pro" in model_ids
    assert "groq-llama-3.3" in model_ids


def test_model_resolution():
    registry = ModelRegistry()

    # OpenAI resolution
    prov_name, prov_model = registry.resolve_provider_model("gpt-4o")
    assert prov_name == "openai"
    assert prov_model == "gpt-4o"

    # Anthropic resolution
    prov_name, prov_model = registry.resolve_provider_model("claude-3-5-sonnet")
    assert prov_name == "anthropic"
    assert prov_model == "claude-3-5-sonnet-20241022"

    # Ollama local resolution
    prov_name, prov_model = registry.resolve_provider_model("llama3")
    assert prov_name == "ollama"
    assert prov_model == "llama3.2"

    # Fallback resolution for custom model
    prov_name, prov_model = registry.resolve_provider_model("custom-raw-model")
    assert prov_name == "openai"
    assert prov_model == "custom-raw-model"


def test_custom_model_registration():
    registry = ModelRegistry()
    custom_model = ModelDefinition(
        model_id="deepseek-r1",
        display_name="DeepSeek R1",
        provider_name="groq",
        provider_model_id="deepseek-r1-distill-llama-70b",
        context_window=128000,
        supports_tools=True,
        supports_streaming=True,
    )

    registry.register_model(custom_model)

    fetched = registry.get_model("deepseek-r1")
    assert fetched is not None
    assert fetched.display_name == "DeepSeek R1"

    prov_name, prov_model = registry.resolve_provider_model("deepseek-r1")
    assert prov_name == "groq"
    assert prov_model == "deepseek-r1-distill-llama-70b"


def test_provider_filtering():
    registry = ModelRegistry()

    anthropic_models = registry.list_models(provider_name="anthropic")
    assert len(anthropic_models) >= 2
    assert all(m.provider_name == "anthropic" for m in anthropic_models)
