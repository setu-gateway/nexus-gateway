import json
from pathlib import Path
from typing import Any

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "marketplace" / "schema" / "plugin-manifest.schema.json"
REGISTRY_PATH = REPO_ROOT / "marketplace" / "registry.json"


def load_schema() -> dict[str, Any]:
    schema: dict[str, Any] = json.loads(SCHEMA_PATH.read_text())
    return schema


def validate_manifest(manifest: dict[str, Any], schema: dict[str, Any] | None = None) -> list[str]:
    """Validate a single plugin manifest against the marketplace schema. Returns a
    list of human-readable error messages - empty if the manifest is valid."""
    schema = schema or load_schema()
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(manifest), key=lambda e: e.path)
    return [f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors]


def validate_registry(registry_path: Path = REGISTRY_PATH) -> dict[str, list[str]]:
    """Validate every entry in registry.json. Returns {plugin_name: [errors]} for
    any entry that failed - empty dict if the whole registry is valid. Also checks
    for duplicate `name` fields, which the JSON Schema itself can't express."""
    schema = load_schema()
    registry = json.loads(registry_path.read_text())
    plugins = registry.get("plugins", [])

    results: dict[str, list[str]] = {}
    seen_names: dict[str, int] = {}
    for i, manifest in enumerate(plugins):
        name = manifest.get("name", f"<entry {i}>")
        errors = validate_manifest(manifest, schema)
        seen_names[name] = seen_names.get(name, 0) + 1
        if errors:
            results[name] = errors

    for name, count in seen_names.items():
        if count > 1:
            results.setdefault(name, []).append(f"duplicate name: appears {count} times in registry.json")

    return results
