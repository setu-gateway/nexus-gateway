import os
from pathlib import Path
from pydantic import ValidationError
import pytest

from packages.shared.config.settings import AppSettings, load_settings, load_yaml_config


def test_default_settings():
    settings = AppSettings()
    assert settings.service_name == "gateway"
    assert settings.port == 8000
    assert settings.log_level == "INFO"
    assert settings.secret_key.get_secret_value() == "default-insecure-dev-secret-key-change-me"


def test_env_var_override(monkeypatch):
    monkeypatch.setenv("PORT", "9090")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-12345")

    settings = load_settings()
    assert settings.port == 9090
    assert settings.log_level == "DEBUG"
    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "sk-test-12345"


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
