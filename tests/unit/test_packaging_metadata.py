from __future__ import annotations

from pathlib import Path

import tomllib


def test_web_test_dependencies_include_httpx() -> None:
    """Clean environments must be able to collect FastAPI web-panel tests."""
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text())

    optional = data["project"]["optional-dependencies"]
    declared = set(optional.get("web", [])) | set(optional.get("dev", []))

    assert any(dep.startswith("httpx") for dep in declared)
