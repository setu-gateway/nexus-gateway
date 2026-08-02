import os
from unittest.mock import patch

from packages.shared.network.retry_config import ProviderRetrySetting, RetryConfig, load_retry_config


def test_for_provider_falls_back_to_default_when_unconfigured():
    config = RetryConfig(default=ProviderRetrySetting(max_retries=3))
    assert config.for_provider("anthropic").max_retries == 3


def test_for_provider_uses_explicit_override():
    config = RetryConfig(
        default=ProviderRetrySetting(max_retries=3),
        providers={"ollama": ProviderRetrySetting(max_retries=1, initial_backoff_sec=0.1)},
    )
    assert config.for_provider("ollama").max_retries == 1
    assert config.for_provider("OLLAMA").max_retries == 1  # case-insensitive
    assert config.for_provider("openai").max_retries == 3


def test_load_retry_config_env_var_overrides_global_default(tmp_path):
    missing_path = str(tmp_path / "does-not-exist.yaml")
    with patch.dict(os.environ, {"RETRY_MAX_RETRIES": "7"}, clear=False):
        config = load_retry_config(yaml_path=missing_path)
    assert config.default.max_retries == 7


def test_load_retry_config_per_provider_env_var(tmp_path):
    missing_path = str(tmp_path / "does-not-exist.yaml")
    with patch.dict(os.environ, {"RETRY_GROQ_MAX_RETRIES": "0"}, clear=False):
        config = load_retry_config(yaml_path=missing_path)
    assert config.for_provider("groq").max_retries == 0
    assert config.for_provider("openai").max_retries == 3  # unaffected


def test_load_retry_config_from_yaml_file(tmp_path):
    yaml_path = tmp_path / "retry.yaml"
    yaml_path.write_text("default:\n  max_retries: 5\nproviders:\n  ollama:\n    max_retries: 0\n")
    config = load_retry_config(yaml_path=str(yaml_path))
    assert config.default.max_retries == 5
    assert config.for_provider("ollama").max_retries == 0
    assert config.for_provider("gemini").max_retries == 5


def test_load_retry_config_missing_file_uses_defaults(tmp_path):
    config = load_retry_config(yaml_path=str(tmp_path / "nope.yaml"))
    assert config.default.max_retries == 3
    assert config.default.backoff_factor == 2.0
