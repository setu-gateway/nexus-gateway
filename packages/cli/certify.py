import importlib
from pathlib import Path

from apps.gateway.certification import CertificationReport, certify_provider
from packages.plugin_sdk import ProviderPlugin


def discover_provider_plugin(provider_name: str) -> ProviderPlugin:
    """Import plugins.providers.<provider_name>.plugin and instantiate its single
    ProviderPlugin subclass. Mirrors the naming convention every built-in provider
    (plugins/providers/{openai,anthropic,gemini,groq,ollama}) already follows, so a
    third-party plugin submitted to the marketplace only needs to match that same
    layout to be certifiable."""
    try:
        module = importlib.import_module(f"plugins.providers.{provider_name}.plugin")
    except ModuleNotFoundError as e:
        raise ValueError(f"No plugin module found at plugins/providers/{provider_name}/plugin.py") from e

    plugin_classes = [
        obj for _, obj in vars(module).items() if isinstance(obj, type) and issubclass(obj, ProviderPlugin) and obj is not ProviderPlugin
    ]
    if not plugin_classes:
        raise ValueError(f"plugins.providers.{provider_name}.plugin defines no ProviderPlugin subclass")
    return plugin_classes[0]()


def list_available_providers() -> list[str]:
    """Scans the filesystem directly rather than via pkgutil.iter_modules: each
    provider directory (plugins/providers/<name>/) is a plain directory with a
    plugin.py but no __init__.py, so it's an implicit namespace package - pkgutil's
    package discovery doesn't reliably walk into those, but a plugin.py's presence is
    a perfectly reliable signal on its own."""
    import plugins.providers as providers_pkg

    providers_dir = Path(providers_pkg.__path__[0])
    return sorted(child.name for child in providers_dir.iterdir() if child.is_dir() and (child / "plugin.py").is_file())


def render_report(report: CertificationReport) -> str:
    lines = [f"Certification report for '{report.provider_name}':", ""]
    for check in report.checks:
        marker = "[PASS]" if check.passed else "[FAIL]"
        line = f"  {marker} {check.name}"
        if check.detail:
            line += f" - {check.detail}"
        lines.append(line)
    lines.append("")
    lines.append(f"Result: {'CERTIFIED' if report.certified else 'NOT CERTIFIED'}")
    lines.append(f"Badge:  {report.badge_markdown}")
    return "\n".join(lines)


async def run_certify(provider_name: str) -> CertificationReport:
    plugin = discover_provider_plugin(provider_name)
    return await certify_provider(plugin)
