import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Application configuration schema with Pydantic Settings & startup validation."""

    service_name: str = Field(default="gateway", description="Name of the service")
    environment: str = Field(default="development", description="Execution environment (development, staging, production, test)")
    port: int = Field(default=8000, description="Service listening port")
    log_level: str = Field(default="INFO", description="Log level verbosity")

    # Database & Cache settings
    database_url: str = Field(
        default="postgresql://setu:setu_pass@localhost:5432/setu_db",
        description="Database connection URL",
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL",
    )
    redis_max_connections: int = Field(default=20, ge=1, description="Redis connection pool size")

    # Security & Secret management
    jwt_secret: SecretStr = Field(
        default=SecretStr("your-super-secret-jwt-key-min-32-chars-long"),
        description="JWT secret signing key",
    )
    jwt_algorithm: str = Field(default="HS256", description="JWT algorithm")
    access_token_expire_minutes: int = Field(default=15, ge=1, description="Access token expiration in minutes")
    refresh_token_expire_days: int = Field(default=30, ge=1, description="Refresh token expiration in days")

    # Provider Secrets
    openai_api_key: SecretStr | None = Field(default=None, description="OpenAI provider API key")
    anthropic_api_key: SecretStr | None = Field(default=None, description="Anthropic provider API key")
    gemini_api_key: SecretStr | None = Field(default=None, description="Google Gemini provider API key")
    groq_api_key: SecretStr | None = Field(default=None, description="Groq provider API key")

    allowed_hosts: list[str] = Field(default=["*"], description="Allowed HTTP hosts")
    request_timeout_seconds: int = Field(default=60, ge=1, description="Request timeout limit in seconds")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        secrets_dir=os.getenv("SECRETS_DIR", None),
    )

    @property
    def is_development(self) -> bool:
        return self.environment.lower() in ("development", "dev")

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in ("production", "prod")

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

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        valid_envs = {"development", "dev", "staging", "production", "prod", "test"}
        if v.lower() not in valid_envs:
            raise ValueError(f"Environment must be one of {valid_envs}")
        return v.lower()

    @field_validator("jwt_algorithm")
    @classmethod
    def validate_jwt_algorithm(cls, v: str) -> str:
        valid_algos = {"HS256", "HS384", "HS512", "RS256", "RS384", "RS512"}
        if v.upper() not in valid_algos:
            raise ValueError(f"JWT algorithm must be one of {valid_algos}")
        return v.upper()

    @field_validator("database_url", "redis_url")
    @classmethod
    def validate_connection_urls(cls, v: str) -> str:
        if not v or not isinstance(v, str):
            raise ValueError("Connection URL cannot be empty")
        return v

    @model_validator(mode="after")
    def validate_production_security(self) -> "AppSettings":
        if self.is_production:
            jwt_secret_val = self.jwt_secret.get_secret_value()
            if "default" in jwt_secret_val or "change-me" in jwt_secret_val:
                raise ValueError("Insecure default JWT_SECRET cannot be used in production environment")
            if len(jwt_secret_val) < 32:
                raise ValueError("JWT_SECRET must be at least 32 characters long in production")
        return self


def load_yaml_config(filepath: str | Path) -> dict[str, Any]:
    """Load configuration dictionary from a YAML file."""
    path = Path(filepath)
    if not path.is_file():
        return {}
    with open(path, encoding="utf-8") as f:
        content = yaml.safe_load(f)
        return content if isinstance(content, dict) else {}


def load_settings(yaml_file: str | Path | None = None) -> AppSettings:
    """Load and validate application settings combining .env, env vars, secrets, and YAML configs."""
    yaml_file_path = yaml_file or os.getenv("CONFIG_YAML_PATH", "config.yaml")
    yaml_dict = load_yaml_config(yaml_file_path)

    settings = AppSettings(**yaml_dict)
    return settings
