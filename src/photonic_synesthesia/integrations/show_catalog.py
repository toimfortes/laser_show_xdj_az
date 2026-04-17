"""Persistent storage for precomputed track show catalogs."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, cast

from photonic_synesthesia.integrations.show_plans import sanitize_show_plan_key


def show_catalog_root() -> Path:
    """Return the user-local root directory for precomputed show catalogs."""
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else (Path.home() / ".local" / "share")
    return base / "photonic_synesthesia" / "show_catalog"


def show_catalog_path(track_key: str) -> Path:
    """Return the JSON path for a precomputed show catalog entry."""
    return show_catalog_root() / f"{sanitize_show_plan_key(track_key)}.json"


def load_show_catalog(track_key: str) -> dict[str, Any] | None:
    """Load a precomputed show catalog entry for the given track key."""
    path = show_catalog_path(track_key)
    if not path.is_file():
        return None
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def save_show_catalog(track_key: str, payload: dict[str, Any]) -> Path:
    """Persist a precomputed show catalog entry for the given track key."""
    path = show_catalog_path(track_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def list_show_catalog_paths() -> list[Path]:
    """Return all persisted show catalog file paths."""
    root = show_catalog_root()
    if not root.is_dir():
        return []
    return sorted(path for path in root.glob("*.json") if path.is_file())
