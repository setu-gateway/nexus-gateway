import re
from dataclasses import dataclass
from typing import Any


@dataclass
class SecretMatch:
    label: str
    matched_text: str


# Deliberately pattern-based (not a generic entropy scanner) - entropy detectors
# false-positive constantly on ordinary hashes/UUIDs/base64 blobs in legitimate
# prompts. Each pattern targets a real, widely-documented secret format, the same
# approach used by gitleaks/trufflehog's default rule sets. Not exhaustive; it's a
# guardrail against the common accidental-paste case, not a DLP system.
SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "aws_access_key_id": re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"),
    "aws_secret_access_key": re.compile(r"(?i)aws_secret_access_key\s*[:=]\s*['\"]?[A-Za-z0-9/+=]{40}['\"]?"),
    "openai_api_key": re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    "anthropic_api_key": re.compile(r"\bsk-ant-[A-Za-z0-9\-_]{20,}\b"),
    "github_token": re.compile(r"\b(ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "slack_token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "stripe_key": re.compile(r"\b(sk|pk|rk)_(live|test)_[A-Za-z0-9]{16,}\b"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "private_key_block": re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
    "generic_bearer_jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    "generic_password_assignment": re.compile(r"(?i)\b(password|passwd|secret|api[_-]?key)\b\s*[:=]\s*['\"]?[^\s'\"]{8,}['\"]?"),
}


def find_secrets(text: str) -> list[SecretMatch]:
    """Scan a single string for any known secret pattern. Returns every match found
    (not just the first) so a policy violation can report exactly what tripped it."""
    matches: list[SecretMatch] = []
    for label, pattern in SECRET_PATTERNS.items():
        for m in pattern.finditer(text):
            matches.append(SecretMatch(label=label, matched_text=m.group(0)))
    return matches


def find_secrets_in_messages(messages: list[dict[str, Any]]) -> list[SecretMatch]:
    """Scan every string `content` field across a chat messages list (Epic: Enterprise
    Policy Engine's block_secrets policy) - content can be a plain string or, for
    multimodal messages, a list of content parts, so both shapes are handled."""
    matches: list[SecretMatch] = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            matches.extend(find_secrets(content))
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    matches.extend(find_secrets(part["text"]))
    return matches
