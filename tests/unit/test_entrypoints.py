import importlib
from pathlib import Path

import tomllib


def test_photonic_web_entrypoint_target_is_importable() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    target = pyproject["project"]["scripts"]["photonic-web"]
    module_name, symbol = target.split(":")

    module = importlib.import_module(module_name)
    entrypoint = getattr(module, symbol)

    assert callable(entrypoint)
