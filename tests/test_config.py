import pytest
from pydantic import ValidationError

from packages.shared.config.settings import AppSettings, load_settings, load_yaml_config


def test_default_settings():
    settings = AppSettings()
    assert settings.service_name == "gateway"
    assert settings.port == 8000
    assert settings.log_level == "INFO"
    assert settings.jwt_algorithm == "HS256"
    assert settings.access_token_expire_minutes == 15
    assert settings.refresh_token_expire_days == 30
    assert settings.is_development is True
    assert settings.is_production is False


def test_jwt_and_env_var_override(monkeypatch):
    monkeypatch.setenv("PORT", "9090")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("JWT_ALGORITHM", "HS512")
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
    monkeypatch.setenv("REFRESH_TOKEN_EXPIRE_DAYS", "60")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-12345")

    settings = load_settings()
    assert settings.port == 9090
    assert settings.log_level == "DEBUG"
    assert settings.jwt_algorithm == "HS512"
    assert settings.access_token_expire_minutes == 30
    assert settings.refresh_token_expire_days == 60
    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "sk-test-12345"


def test_production_config_validation():
    # Production with weak/default secret key should fail validation
    with pytest.raises(ValidationError):
        AppSettings(
            environment="production",
            jwt_secret="default-insecure-key",
        )

    # Valid production settings
    prod_settings = AppSettings(
        environment="production",
        jwt_secret="a-very-long-secure-random-jwt-secret-key-32-chars",
    )
    assert prod_settings.is_production is True
    assert prod_settings.jwt_secret.get_secret_value() == "a-very-long-secure-random-jwt-secret-key-32-chars"


def test_invalid_jwt_algorithm():
    with pytest.raises(ValidationError):
        AppSettings(jwt_algorithm="UNSUPPORTED_ALGO")


def test_yaml_config_loading(tmp_path):
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text("port: 8888\nenvironment: staging\nlog_level: WARNING\n")

    yaml_data = load_yaml_config(yaml_file)
    assert yaml_data["port"] == 8888
    assert yaml_data["environment"] == "staging"

    settings = load_settings(yaml_file=yaml_file)
    assert settings.port == 8888
    assert settings.environment == "staging"
    assert settings.log_level == "WARNING"


def test_startup_validation_invalid_port():
    with pytest.raises(ValidationError):
        AppSettings(port=999999)


def test_startup_validation_invalid_log_level():
    with pytest.raises(ValidationError):
        AppSettings(log_level="SUPER_VERBOSE")
