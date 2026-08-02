import os
from typing import Any

import yaml
from pydantic import BaseModel, Field

from packages.shared.logging.logger import get_logger

logger = get_logger("providers_config")


class ProviderSetting(BaseModel):
    enabled: bool = True
    base_url: str | None = None
    api_key: str | None = None
    timeout_seconds: float = 30.0


class ProvidersConfig(BaseModel):
    providers: dict[str, ProviderSetting] = Field(
        default_factory=lambda: {
            "openai": ProviderSetting(enabled=True),
            "ollama": ProviderSetting(enabled=True),
            "anthropic": ProviderSetting(enabled=False),
            "gemini": ProviderSetting(enabled=True),
            "groq": ProviderSetting(enabled=True),
        }
    )


def load_providers_config(yaml_path: str | None = None) -> ProvidersConfig:
    """Load provider settings from YAML overlay file and environment variables."""
    config_dict: dict[str, Any] = {}

    path = yaml_path or os.getenv("PROVIDERS_CONFIG_PATH", "providers.yaml")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                if loaded and "providers" in loaded:
                    config_dict = loaded["providers"]
        except Exception as e:
            logger.warning(f"Could not load providers config from '{path}', falling back to defaults: {e}")

    providers_map: dict[str, ProviderSetting] = {}
    known_providers = ["openai", "ollama", "anthropic", "gemini", "groq"]

    for name in known_providers:
        env_enabled_val = os.getenv(f"PROVIDER_{name.upper()}_ENABLED")
        if env_enabled_val is not None:
            enabled = env_enabled_val.lower() in ("true", "1", "yes")
        elif name in config_dict:
            enabled = config_dict[name].get("enabled", True)
        else:
            enabled = name != "anthropic"

        base_url = os.getenv(f"PROVIDER_{name.upper()}_BASE_URL") or config_dict.get(name, {}).get("base_url")

        providers_map[name] = ProviderSetting(
            enabled=enabled,
            base_url=base_url,
        )

    return ProvidersConfig(providers=providers_map)
