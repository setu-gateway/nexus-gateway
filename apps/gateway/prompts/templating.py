import re
from typing import Any

# Deliberately a plain regex substitution, not a general templating engine (Jinja2 et
# al.): prompt templates are {{variable}} text fill-ins, not a place to run arbitrary
# expressions/loops against untrusted input, and the simpler mechanism is easier to
# reason about for both security and "why didn't this render" support questions.
_VARIABLE_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def _text_parts(content: Any) -> list[str]:
    """Pulls out every substitutable string from a message's `content` - either the
    content itself (plain-text messages) or each `text` field of a multimodal
    content-part list (OpenAI's `[{"type": "text", "text": "..."}, {"type":
    "image_url", ...}]` shape, same as _detects_vision_request in openai_v1.py)."""
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        return [part["text"] for part in content if isinstance(part, dict) and isinstance(part.get("text"), str)]
    return []


def extract_variables(messages: list[dict[str, Any]]) -> list[str]:
    """The sorted, de-duplicated {{variable}} names referenced anywhere in a
    template's messages."""
    found: set[str] = set()
    for message in messages:
        for text in _text_parts(message.get("content")):
            found.update(_VARIABLE_PATTERN.findall(text))
    return sorted(found)


def _substitute(text: str, variables: dict[str, Any]) -> str:
    def _replace(match: "re.Match[str]") -> str:
        name = match.group(1)
        return str(variables[name]) if name in variables else match.group(0)

    return _VARIABLE_PATTERN.sub(_replace, text)


def render_messages(messages: list[dict[str, Any]], variables: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Substitutes {{variable}} placeholders with values from `variables`.

    Returns (rendered_messages, missing_variable_names). A variable referenced in the
    template but absent from `variables` is left as a literal `{{name}}` in the
    output and also reported in `missing`, so a caller with no rendering context of
    its own (this function is intentionally not the one deciding what a missing
    variable means for the request) can either error or fall back as it sees fit.
    """
    missing = sorted(set(extract_variables(messages)) - variables.keys())

    rendered: list[dict[str, Any]] = []
    for message in messages:
        new_message = dict(message)
        content = message.get("content")
        if isinstance(content, str):
            new_message["content"] = _substitute(content, variables)
        elif isinstance(content, list):
            new_message["content"] = [
                {**part, "text": _substitute(part["text"], variables)}
                if isinstance(part, dict) and isinstance(part.get("text"), str)
                else part
                for part in content
            ]
        rendered.append(new_message)

    return rendered, missing
