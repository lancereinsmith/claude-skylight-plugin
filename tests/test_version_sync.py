"""Guard: the version is declared in two places; they must agree."""

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_pyproject_and_plugin_manifest_versions_match():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    assert pyproject["project"]["version"] == manifest["version"]
