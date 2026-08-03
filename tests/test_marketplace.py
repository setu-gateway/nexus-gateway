from packages.cli.main import main
from packages.cli.marketplace import validate_manifest, validate_registry

VALID_MANIFEST = {
    "name": "my-plugin",
    "category": "providers",
    "version": "1.0.0",
    "author": "Someone",
    "license": "Apache-2.0",
    "repository": "https://github.com/someone/my-plugin",
    "entryPoint": "my_plugin.plugin.MyPlugin",
    "description": "A plugin.",
}


def test_valid_manifest_has_no_errors():
    assert validate_manifest(VALID_MANIFEST) == []


def test_missing_required_field_is_reported():
    manifest = {k: v for k, v in VALID_MANIFEST.items() if k != "license"}
    errors = validate_manifest(manifest)
    assert any("license" in e for e in errors)


def test_invalid_category_is_reported():
    manifest = {**VALID_MANIFEST, "category": "not-a-real-category"}
    errors = validate_manifest(manifest)
    assert any("category" in e for e in errors)


def test_invalid_name_pattern_is_reported():
    manifest = {**VALID_MANIFEST, "name": "Not Lowercase!"}
    errors = validate_manifest(manifest)
    assert any("name" in e for e in errors)


def test_real_registry_json_is_valid():
    assert validate_registry() == {}


def test_cli_marketplace_validate_registry_exits_zero(capsys):
    assert main(["marketplace", "validate"]) == 0
    assert "valid" in capsys.readouterr().out


def test_cli_marketplace_validate_manifest_file(tmp_path, capsys):
    import json

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(VALID_MANIFEST))

    assert main(["marketplace", "validate", "--manifest", str(manifest_path)]) == 0
    assert "valid" in capsys.readouterr().out


def test_cli_marketplace_validate_bad_manifest_file_exits_nonzero(tmp_path, capsys):
    import json

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"name": "bad name"}))

    assert main(["marketplace", "validate", "--manifest", str(manifest_path)]) == 1
    assert "INVALID" in capsys.readouterr().out
