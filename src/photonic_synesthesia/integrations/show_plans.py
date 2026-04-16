"""Persistent storage for generated and edited show plans."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, cast


def show_plan_root() -> Path:
    """Return the user-local root directory for persisted show plans."""
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else (Path.home() / ".local" / "share")
    return base / "photonic_synesthesia" / "show_plans"


def sanitize_show_plan_key(value: str) -> str:
    """Normalize a track key into a filesystem-safe stem."""
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in value.strip())
    compact = "_".join(segment for segment in cleaned.split("_") if segment)
    return compact or "unknown_track"


def show_plan_path(track_key: str) -> Path:
    """Return the JSON path for a persisted show plan."""
    return show_plan_root() / f"{sanitize_show_plan_key(track_key)}.json"


def load_show_plan(track_key: str) -> dict[str, Any] | None:
    """Load a persisted show plan for the given track key."""
    path = show_plan_path(track_key)
    if not path.is_file():
        return None
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def save_show_plan(track_key: str, payload: dict[str, Any]) -> Path:
    """Persist a show plan JSON payload for the given track key."""
    path = show_plan_path(track_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path
