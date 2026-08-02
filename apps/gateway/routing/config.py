import os
from typing import Any

import yaml
from pydantic import BaseModel, Field

from apps.gateway.routing.policies import RoutingPolicy
from packages.shared.logging.logger import get_logger

logger = get_logger("routing_config")


class RoutingConfig(BaseModel):
    """Organization/deployment-level routing defaults.

    Per-request callers can still override policy, required capability, and preferred
    provider explicitly (e.g. from an org/project setting) - this is just the fallback
    when nothing more specific is supplied.
    """

    default_policy: RoutingPolicy = RoutingPolicy.HIGHEST_AVAILABILITY
    weights: dict[str, float] = Field(default_factory=dict, description="Provider name -> weight, used by the 'weighted' policy")
    preferred_provider: str | None = Field(default=None, description="Provider name used by the 'user_preference' policy")


def load_routing_config(yaml_path: str | None = None) -> RoutingConfig:
    """Load routing configuration from a YAML overlay file and environment variables.

    Mirrors packages/shared/config/providers_config.py's loading pattern: env vars take
    precedence over the YAML file, which takes precedence over built-in defaults.
    """
    config_dict: dict[str, Any] = {}

    path = yaml_path or os.getenv("ROUTING_CONFIG_PATH", "routing.yaml")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                if isinstance(loaded, dict):
                    config_dict = loaded
        except Exception as e:
            logger.warning(f"Could not load routing config from '{path}', falling back to defaults: {e}")

    policy_name = os.getenv("ROUTING_DEFAULT_POLICY") or config_dict.get("default_policy")
    try:
        default_policy = RoutingPolicy(policy_name) if policy_name else RoutingPolicy.HIGHEST_AVAILABILITY
    except ValueError:
        default_policy = RoutingPolicy.HIGHEST_AVAILABILITY

    weights = config_dict.get("routing", {}) if isinstance(config_dict.get("routing"), dict) else {}
    preferred_provider = os.getenv("ROUTING_PREFERRED_PROVIDER") or config_dict.get("preferred_provider")

    return RoutingConfig(
        default_policy=default_policy,
        weights=weights,
        preferred_provider=preferred_provider,
    )
