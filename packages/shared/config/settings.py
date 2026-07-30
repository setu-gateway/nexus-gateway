import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
import yaml


class AppSettings(BaseSettings):
    """Application configuration schema with startup validation."""

    service_name: str = Field(default="gateway", description="Name of the service")
    environment: str = Field(default="development", description="Execution environment")
    port: int = Field(default=8000, description="Service listening port")
    log_level: str = Field(default="INFO", description="Log level verbosity")

    database_url: str = Field(
        default="postgresql://setu:setu_pass@localhost:5432/setu_db",
        description="Database connection URL",
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL",
    )
    redis_max_connections: int = Field(default=20, ge=1, description="Redis connection pool size")

    secret_key: SecretStr = Field(
        default=SecretStr("default-insecure-dev-secret-key-change-me"),
        description="Application secret key",
    )
    openai_api_key: Optional[SecretStr] = Field(default=None, description="OpenAI provider API key")
    anthropic_api_key: Optional[SecretStr] = Field(default=None, description="Anthropic provider API key")
    gemini_api_key: Optional[SecretStr] = Field(default=None, description="Google Gemini provider API key")

    allowed_hosts: List[str] = Field(default=["*"], description="Allowed HTTP hosts")
    request_timeout_seconds: int = Field(default=60, ge=1, description="Request timeout limit in seconds")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        secrets_dir=os.getenv("SECRETS_DIR", None),
    )

    @field_validator("port")
    @classmethod
    def validate_port_range(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ValueError("Port must be between 1 and 65535")
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in valid_levels:
            raise ValueError(f"Log level must be one of {valid_levels}")
        return v.upper()

    @field_validator("database_url", "redis_url")
    @classmethod
    def validate_connection_urls(cls, v: str) -> str:
        if not v or not isinstance(v, str):
            raise ValueError("Connection URL cannot be empty")
        return v


def load_yaml_config(filepath: Union[str, Path]) -> Dict[str, Any]:
    """Load configuration dictionary from a YAML file."""
    path = Path(filepath)
    if not path.is_file():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        content = yaml.safe_load(f)
        return content if isinstance(content, dict) else {}


def load_settings(yaml_file: Optional[Union[str, Path]] = None) -> AppSettings:
    """Load and validate application settings combining .env, environment variables, secrets, and YAML configs."""
    yaml_file_path = yaml_file or os.getenv("CONFIG_YAML_PATH", "config.yaml")
    yaml_dict = load_yaml_config(yaml_file_path)

    settings = AppSettings(**yaml_dict)
    return settings
