import os
import tempfile
import pytest

from apps.gateway.db.models.provider_config import ProviderConfigModel
from packages.shared.config.providers_config import ProviderSetting, ProvidersConfig, load_providers_config


def test_provider_config_db_model_instantiation():
    config = ProviderConfigModel(
        provider_name="openai",
        enabled=True,
        base_url="https://api.openai.com/v1",
    )
    assert config.provider_name == "openai"
    assert config.enabled is True
    assert config.base_url == "https://api.openai.com/v1"


def test_load_providers_config_defaults():
    config = load_providers_config(yaml_path="nonexistent.yaml")
    assert isinstance(config, ProvidersConfig)
    assert config.providers["openai"].enabled is True
    assert config.providers["ollama"].enabled is True
    assert config.providers["anthropic"].enabled is False


def test_load_providers_config_yaml_overlay():
    yaml_content = """
providers:
  openai:
    enabled: true
  ollama:
    enabled: true
  anthropic:
    enabled: false
  groq:
    enabled: true
"""
    with tempfile.NamedTemporaryFile("w+", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        f.flush()
        temp_path = f.name

    try:
        config = load_providers_config(yaml_path=temp_path)
        assert config.providers["openai"].enabled is True
        assert config.providers["ollama"].enabled is True
        assert config.providers["anthropic"].enabled is False
    finally:
        os.remove(temp_path)


def test_load_providers_config_env_overrides(monkeypatch):
    monkeypatch.setenv("PROVIDER_ANTHROPIC_ENABLED", "true")
    monkeypatch.setenv("PROVIDER_OPENAI_ENABLED", "false")

    config = load_providers_config(yaml_path="nonexistent.yaml")
    assert config.providers["anthropic"].enabled is True
    assert config.providers["openai"].enabled is False
