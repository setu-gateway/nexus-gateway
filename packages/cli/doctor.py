import os
from dataclasses import dataclass

import httpx

from packages.shared.config.providers_config import load_providers_config
from packages.shared.config.settings import load_settings


@dataclass
class DoctorCheck:
    name: str
    ok: bool
    detail: str = ""


def check_env_file() -> DoctorCheck:
    exists = os.path.isfile(".env")
    return DoctorCheck(
        "`.env` file present",
        exists,
        "" if exists else "Not found in current directory - copy .env.example to .env and fill in your secrets",
    )


def check_settings_load() -> DoctorCheck:
    """`setu config validate`'s core check: settings.py validators (port range, log
    level, environment name, ...) all run here, so a bad .env value is caught as a
    clear failure instead of a confusing error later at request time."""
    try:
        settings = load_settings()
        return DoctorCheck("Settings load and validate", True, f"environment={settings.environment}, port={settings.port}")
    except Exception as e:
        return DoctorCheck("Settings load and validate", False, str(e))


def check_providers_config() -> DoctorCheck:
    try:
        config = load_providers_config()
        enabled = [name for name, setting in config.providers.items() if setting.enabled]
        return DoctorCheck("Provider config loads correctly", True, f"enabled: {', '.join(enabled) or 'none'}")
    except Exception as e:
        return DoctorCheck("Provider config loads correctly", False, str(e))


async def check_gateway_reachable(base_url: str) -> DoctorCheck:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{base_url}/health", timeout=5.0)
    except Exception as e:
        return DoctorCheck("Gateway reachable", False, f"{base_url}: {e}")

    if resp.status_code != 200:
        return DoctorCheck("Gateway reachable", False, f"{base_url} returned HTTP {resp.status_code}")

    data = resp.json()
    components = data.get("components", {})
    detail = f"status={data.get('status')}, " + ", ".join(f"{k}={'ok' if v else 'FAIL'}" for k, v in components.items())
    return DoctorCheck("Gateway reachable", data.get("status") != "unhealthy", detail)


def run_config_checks() -> list[DoctorCheck]:
    """Local-only checks (`setu config validate`) - no running gateway required."""
    return [check_env_file(), check_settings_load(), check_providers_config()]


async def run_doctor_checks(base_url: str) -> list[DoctorCheck]:
    """Full environment sweep (`setu doctor`) - local config plus a live reachability
    check against a running gateway."""
    checks = run_config_checks()
    checks.append(await check_gateway_reachable(base_url))
    return checks
