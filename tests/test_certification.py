import pytest

from apps.gateway.certification import certify_provider
from plugins.providers.ollama.plugin import OllamaProviderPlugin
from plugins.providers.openai.plugin import OpenAIProviderPlugin


@pytest.mark.asyncio
async def test_openai_reference_plugin_passes_certification():
    report = await certify_provider(OpenAIProviderPlugin())
    assert report.provider_name == "openai"
    assert {c.name for c in report.checks} == {"chat", "streaming", "embeddings", "retry", "health", "authentication"}
    failures = [c for c in report.checks if not c.passed]
    assert not failures, f"unexpected certification failures: {failures}"
    assert report.certified is True


@pytest.mark.asyncio
async def test_ollama_reference_plugin_fails_only_the_authentication_check():
    # Ollama is a self-hosted, typically-unauthenticated local server - the reference
    # plugin genuinely has no api_key/token attribute, so it should NOT be certified
    # as having an authentication story. Everything else should still pass.
    report = await certify_provider(OllamaProviderPlugin())
    by_name = {c.name: c.passed for c in report.checks}
    assert by_name["authentication"] is False
    assert all(passed for name, passed in by_name.items() if name != "authentication")
    assert report.certified is False


@pytest.mark.asyncio
async def test_certified_badge_is_green_when_all_checks_pass():
    report = await certify_provider(OpenAIProviderPlugin())
    assert "brightgreen" in report.badge_markdown


def test_uncertified_badge_is_red_when_a_check_fails():
    from apps.gateway.certification.checker import CertificationCheck, CertificationReport

    report = CertificationReport(
        provider_name="broken",
        checks=[CertificationCheck(name="chat", passed=False, detail="boom")],
    )
    assert report.certified is False
    assert "red" in report.badge_markdown
