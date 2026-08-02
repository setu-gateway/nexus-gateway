import os
from typing import Any

import yaml
from pydantic import BaseModel, Field

from packages.shared.logging.logger import get_logger

logger = get_logger("retry_config")


class ProviderRetrySetting(BaseModel):
    max_retries: int = Field(default=3, ge=0)
    initial_backoff_sec: float = Field(default=0.5, gt=0)
    backoff_factor: float = Field(default=2.0, ge=1.0)


class RetryConfig(BaseModel):
    """Provider-aware retry settings (Epic 4.4). A provider with tighter latency
    guarantees (e.g. a local Ollama daemon) or a provider known to rate-limit
    aggressively can be tuned independently of the global default."""

    default: ProviderRetrySetting = Field(default_factory=ProviderRetrySetting)
    providers: dict[str, ProviderRetrySetting] = Field(default_factory=dict)

    def for_provider(self, provider_name: str) -> ProviderRetrySetting:
        return self.providers.get(provider_name.lower(), self.default)


def load_retry_config(yaml_path: str | None = None) -> RetryConfig:
    """Load retry configuration from a YAML overlay file and environment variables,
    mirroring the loading pattern used by providers_config.py / routing config.py."""
    config_dict: dict[str, Any] = {}

    path = yaml_path or os.getenv("RETRY_CONFIG_PATH", "retry.yaml")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                if isinstance(loaded, dict):
                    config_dict = loaded
        except Exception as e:
            logger.warning(f"Failed to load retry config overlay from '{path}': {e}")

    default_dict = config_dict.get("default", {}) if isinstance(config_dict.get("default"), dict) else {}
    default_setting = ProviderRetrySetting(**default_dict)

    env_max_retries = os.getenv("RETRY_MAX_RETRIES")
    if env_max_retries is not None:
        default_setting = default_setting.model_copy(update={"max_retries": int(env_max_retries)})

    providers_dict = config_dict.get("providers", {}) if isinstance(config_dict.get("providers"), dict) else {}
    providers: dict[str, ProviderRetrySetting] = {}
    for name, overrides in providers_dict.items():
        if isinstance(overrides, dict):
            providers[name.lower()] = ProviderRetrySetting(**{**default_setting.model_dump(), **overrides})

    for name in ("openai", "anthropic", "gemini", "ollama", "groq"):
        env_val = os.getenv(f"RETRY_{name.upper()}_MAX_RETRIES")
        if env_val is not None:
            base = providers.get(name, default_setting)
            providers[name] = base.model_copy(update={"max_retries": int(env_val)})

    return RetryConfig(default=default_setting, providers=providers)
