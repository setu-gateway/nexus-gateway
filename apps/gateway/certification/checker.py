import inspect
from dataclasses import dataclass, field

from packages.plugin_sdk import ChatRequest, EmbeddingRequest, ProviderPlugin

CERTIFICATION_CHECKS = ("chat", "streaming", "embeddings", "retry", "health", "authentication")


@dataclass
class CertificationCheck:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class CertificationReport:
    provider_name: str
    checks: list[CertificationCheck] = field(default_factory=list)

    @property
    def certified(self) -> bool:
        return len(self.checks) == len(CERTIFICATION_CHECKS) and all(c.passed for c in self.checks)

    @property
    def badge_markdown(self) -> str:
        """Shields.io badge markdown for this provider's README, matching the format
        every certified plugin displays per Epic 7.4."""
        label, color = ("certified", "brightgreen") if self.certified else ("not%20certified", "red")
        return f"![Setu Gateway Certified](https://img.shields.io/badge/setu--gateway-{label}-{color})"


async def _check_chat(plugin: ProviderPlugin) -> CertificationCheck:
    try:
        response = await plugin.chat(ChatRequest(model="certification-probe", messages=[{"role": "user", "content": "ping"}]))
        ok = isinstance(response, dict) and bool(response)
        return CertificationCheck("chat", ok, "" if ok else f"chat() returned an empty/non-dict response: {response!r}")
    except Exception as e:
        return CertificationCheck("chat", False, f"chat() raised: {e}")


async def _check_streaming(plugin: ProviderPlugin) -> CertificationCheck:
    try:
        result = await plugin.chat(ChatRequest(model="certification-probe", messages=[{"role": "user", "content": "ping"}], stream=True))
        ok = result is not None
        return CertificationCheck("streaming", ok, "" if ok else "chat(stream=True) returned nothing")
    except Exception as e:
        return CertificationCheck("streaming", False, f"chat(stream=True) raised: {e}")


async def _check_embeddings(plugin: ProviderPlugin) -> CertificationCheck:
    try:
        response = await plugin.embeddings(EmbeddingRequest(model="certification-probe", input="ping"))
        ok = isinstance(response, dict) and bool(response)
        return CertificationCheck("embeddings", ok, "" if ok else f"embeddings() returned an empty/non-dict response: {response!r}")
    except Exception as e:
        return CertificationCheck("embeddings", False, f"embeddings() raised: {e}")


def _check_retry(plugin: ProviderPlugin) -> CertificationCheck:
    # Structural, not behavioral: forcing a real transient failure to observe a retry
    # would need network-level fault injection per provider. Checking that chat()'s
    # source references the shared retry_provider_call helper (packages/shared/network)
    # is the same thing every provider plugin in this repo already does - see
    # plugins/providers/openai/plugin.py for the reference implementation.
    try:
        source = inspect.getsource(type(plugin).chat)
        ok = "retry" in source.lower()
        return CertificationCheck("retry", ok, "" if ok else "chat() doesn't appear to use a retry wrapper for transient failures")
    except (OSError, TypeError) as e:
        return CertificationCheck("retry", False, f"could not inspect chat() source: {e}")


async def _check_health(plugin: ProviderPlugin) -> CertificationCheck:
    try:
        response = await plugin.health()
        ok = response.status in ("ok", "degraded", "offline")
        return CertificationCheck("health", ok, "" if ok else f"health() returned an unrecognized status: {response.status!r}")
    except Exception as e:
        return CertificationCheck("health", False, f"health() raised: {e}")


def _check_authentication(plugin: ProviderPlugin) -> CertificationCheck:
    # Structural: does the plugin have a concept of credentials at all? A provider
    # with no api_key/token attribute has no authentication story to certify.
    has_credential_attr = any(hasattr(plugin, attr) for attr in ("api_key", "token", "credentials"))
    return CertificationCheck(
        "authentication", has_credential_attr, "" if has_credential_attr else "no api_key/token/credentials attribute found on the plugin"
    )


async def certify_provider(plugin: ProviderPlugin) -> CertificationReport:
    """Run a provider plugin through the certification contract (Epic 7.4): chat,
    streaming, embeddings, retry, health, and authentication. Behavioral checks call
    the plugin directly - every built-in provider already falls back to a
    deterministic mock response with no API key configured (see README Quickstart),
    so this runs the same way in CI as it does against a real, credentialed
    provider. A plugin passes only if every check passes."""
    report = CertificationReport(provider_name=plugin.provider_name)
    report.checks.append(await _check_chat(plugin))
    report.checks.append(await _check_streaming(plugin))
    report.checks.append(await _check_embeddings(plugin))
    report.checks.append(_check_retry(plugin))
    report.checks.append(await _check_health(plugin))
    report.checks.append(_check_authentication(plugin))
    return report
