import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import jsonschema

from packages.shared.logging.logger import get_logger

logger = get_logger("eval_scorers")


@dataclass
class ScoreResult:
    """The outcome of scoring one case's actual response. `score` is 0.0-1.0; every
    current scorer is pass/fail (1.0 or 0.0), but the field is continuous so a future
    scorer (e.g. fuzzy/semantic similarity) can report a partial score without a schema
    change. `details` carries scorer-specific diagnostics (what was expected vs. found)
    for display in the run's results view."""

    passed: bool
    score: float
    details: dict[str, Any] = field(default_factory=dict)


def _extract_text(response: dict[str, Any]) -> str:
    """Pull the assistant's message text out of an OpenAI-shaped chat completion
    response. Returns "" for any unexpected/empty shape rather than raising, so a
    provider error or empty completion scores as a clean miss instead of crashing the
    run."""
    try:
        content = response["choices"][0]["message"].get("content")
        return content if isinstance(content, str) else ""
    except (KeyError, IndexError, TypeError):
        return ""


def _extract_tool_calls(response: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        return response["choices"][0]["message"].get("tool_calls") or []
    except (KeyError, IndexError, TypeError):
        return []


class BaseScorer(ABC):
    """Pluggable scoring strategy for one EvalCase. `expected` and `config` come
    straight from EvalCase.expected_output / scorer_config - each subclass defines its
    own expected shape (documented on the class)."""

    @abstractmethod
    def score(self, response: dict[str, Any], expected: Any, config: dict[str, Any] | None) -> ScoreResult: ...


class ExactMatchScorer(BaseScorer):
    """expected_output: str. scorer_config: {case_sensitive: bool = True,
    strip_whitespace: bool = True}."""

    def score(self, response: dict[str, Any], expected: Any, config: dict[str, Any] | None) -> ScoreResult:
        config = config or {}
        case_sensitive = config.get("case_sensitive", True)
        strip_whitespace = config.get("strip_whitespace", True)

        actual = _extract_text(response)
        expected_str = "" if expected is None else str(expected)
        a, e = actual, expected_str
        if strip_whitespace:
            a, e = a.strip(), e.strip()
        if not case_sensitive:
            a, e = a.lower(), e.lower()

        passed = a == e
        return ScoreResult(passed=passed, score=1.0 if passed else 0.0, details={"actual": actual, "expected": expected_str})


class ContainsScorer(BaseScorer):
    """expected_output: str or list[str] (required substrings). scorer_config:
    {case_sensitive: bool = False, mode: "all" | "any" = "all"}."""

    def score(self, response: dict[str, Any], expected: Any, config: dict[str, Any] | None) -> ScoreResult:
        config = config or {}
        case_sensitive = config.get("case_sensitive", False)
        mode = config.get("mode", "all")

        substrings = expected if isinstance(expected, list) else [expected]
        actual = _extract_text(response)
        haystack = actual if case_sensitive else actual.lower()

        found: list[Any] = []
        missing: list[Any] = []
        for s in substrings:
            needle = str(s) if case_sensitive else str(s).lower()
            (found if needle in haystack else missing).append(s)

        passed = (len(found) > 0) if mode == "any" else (not missing)
        score = (len(found) / len(substrings)) if substrings else 0.0
        return ScoreResult(passed=passed, score=score, details={"actual": actual, "found": found, "missing": missing})


class StructuredOutputScorer(BaseScorer):
    """expected_output: a JSON Schema object. The actual response text must parse as
    JSON and validate against it - two independent failure modes (not valid JSON at
    all vs. valid JSON that violates the schema), both reported via `details`."""

    def score(self, response: dict[str, Any], expected: Any, config: dict[str, Any] | None) -> ScoreResult:
        actual_text = _extract_text(response)
        try:
            parsed = json.loads(actual_text)
        except (json.JSONDecodeError, TypeError):
            return ScoreResult(passed=False, score=0.0, details={"error": "response is not valid JSON", "actual": actual_text})

        try:
            jsonschema.validate(instance=parsed, schema=expected)
        except jsonschema.exceptions.ValidationError as e:
            return ScoreResult(
                passed=False,
                score=0.0,
                details={"error": e.message, "path": list(e.absolute_path), "actual": parsed},
            )
        except jsonschema.exceptions.SchemaError as e:
            return ScoreResult(passed=False, score=0.0, details={"error": f"invalid JSON Schema: {e.message}"})

        return ScoreResult(passed=True, score=1.0, details={"actual": parsed})


class ToolCallSuccessScorer(BaseScorer):
    """expected_output: {"tool_name": str, "arguments": Optional[dict]}. Passes if the
    response includes a tool call for `tool_name`, and (when `arguments` is given)
    that call's arguments are a superset match of the expected key/value pairs - a
    case can assert only the arguments it cares about rather than the whole payload.

    Note: the gateway's provider adapters don't forward `tools` upstream yet (see
    OpenAIRequest.tools' docstring), so a response produced through the live chat
    endpoint won't currently contain tool_calls - this scorer is exercised today via
    directly-supplied fixture responses and is ready for when tool-calling ships.
    """

    def score(self, response: dict[str, Any], expected: Any, config: dict[str, Any] | None) -> ScoreResult:
        if not isinstance(expected, dict) or not expected.get("tool_name"):
            return ScoreResult(passed=False, score=0.0, details={"error": "expected_output must include 'tool_name'"})

        expected_name = expected["tool_name"]
        expected_args: dict[str, Any] | None = expected.get("arguments")
        tool_calls = _extract_tool_calls(response)

        for call in tool_calls:
            fn = call.get("function", {})
            if fn.get("name") != expected_name:
                continue
            if not expected_args:
                return ScoreResult(passed=True, score=1.0, details={"matched_call": call})
            try:
                actual_args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                continue
            if isinstance(actual_args, dict) and all(actual_args.get(k) == v for k, v in expected_args.items()):
                return ScoreResult(passed=True, score=1.0, details={"matched_call": call})

        return ScoreResult(
            passed=False,
            score=0.0,
            details={"error": f"no tool call matching '{expected_name}' found", "tool_calls": tool_calls},
        )


SCORER_REGISTRY: dict[str, type[BaseScorer]] = {
    "exact_match": ExactMatchScorer,
    "contains": ContainsScorer,
    "structured_output": StructuredOutputScorer,
    "tool_call_success": ToolCallSuccessScorer,
}


def is_valid_scorer_type(scorer_type: str) -> bool:
    return scorer_type in SCORER_REGISTRY


def get_scorer(scorer_type: str) -> BaseScorer:
    scorer_cls = SCORER_REGISTRY.get(scorer_type)
    if not scorer_cls:
        raise ValueError(f"Unknown scorer type '{scorer_type}'. Supported: {sorted(SCORER_REGISTRY)}")
    return scorer_cls()


def score_response(scorer_type: str, response: dict[str, Any], expected: Any, config: dict[str, Any] | None = None) -> ScoreResult:
    return get_scorer(scorer_type).score(response, expected, config)


def validate_case_definition(scorer_type: str, expected_output: Any) -> None:
    """Eagerly checks that `expected_output` is a shape the given scorer can actually
    use, so a malformed case is rejected at creation time (a clear 400) instead of
    silently scoring "failed" on every future run. Raises ValueError with a message
    suitable for direct display to the API caller.
    """
    if not is_valid_scorer_type(scorer_type):
        raise ValueError(f"Unknown scorer_type '{scorer_type}'. Supported: {sorted(SCORER_REGISTRY)}")

    if scorer_type == "contains":
        if not isinstance(expected_output, (str, list)):
            raise ValueError("expected_output for 'contains' must be a string or a list of strings")
        if isinstance(expected_output, list) and not all(isinstance(s, str) for s in expected_output):
            raise ValueError("expected_output for 'contains' must be a string or a list of strings")
    elif scorer_type == "structured_output":
        if not isinstance(expected_output, dict):
            raise ValueError("expected_output for 'structured_output' must be a JSON Schema object")
        try:
            jsonschema.Draft202012Validator.check_schema(expected_output)
        except jsonschema.exceptions.SchemaError as e:
            raise ValueError(f"expected_output is not a valid JSON Schema: {e.message}") from e
    elif scorer_type == "tool_call_success":
        if not isinstance(expected_output, dict) or not expected_output.get("tool_name"):
            raise ValueError("expected_output for 'tool_call_success' must be an object with a 'tool_name' key")
    elif scorer_type == "exact_match":
        if expected_output is None:
            raise ValueError("expected_output for 'exact_match' must not be null")
