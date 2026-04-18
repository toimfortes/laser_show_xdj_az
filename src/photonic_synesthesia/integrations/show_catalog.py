"""Persistent storage for precomputed track show catalogs."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from photonic_synesthesia.core.logging import get_logger
from photonic_synesthesia.integrations.show_plans import sanitize_show_plan_key

logger = get_logger(__name__)

SCHEMA_VERSION = 1
_SCHEMA_KEY = "_schema_version"


def show_catalog_root() -> Path:
    """Return the user-local root directory for precomputed show catalogs."""
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else (Path.home() / ".local" / "share")
    return base / "photonic_synesthesia" / "show_catalog"


def show_catalog_path(track_key: str) -> Path:
    """Return the JSON path for a precomputed show catalog entry."""
    return show_catalog_root() / f"{sanitize_show_plan_key(track_key)}.json"


def load_show_catalog(track_key: str) -> dict[str, Any] | None:
    """Load a precomputed show catalog entry for the given track key.

    Returns None on:
    - missing file
    - malformed JSON (logged at warning level)
    - payload root is not a JSON object (logged)
    Returns the payload with a warning if the stored _schema_version is
    newer than this code understands. Older versions are forward-compatible
    (we don't delete fields; callers handle key-presence themselves).
    """
    path = show_catalog_path(track_key)
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("show_catalog load failed", path=str(path), error=str(exc))
        return None
    if not isinstance(payload, dict):
        logger.warning(
            "show_catalog payload is not a JSON object",
            path=str(path),
            type=type(payload).__name__,
        )
        return None
    stored_version = payload.get(_SCHEMA_KEY)
    if isinstance(stored_version, int) and stored_version > SCHEMA_VERSION:
        logger.warning(
            "show_catalog schema is newer than this build",
            path=str(path),
            stored=stored_version,
            local=SCHEMA_VERSION,
        )
    return payload


def save_show_catalog(track_key: str, payload: dict[str, Any]) -> Path:
    """Persist a precomputed show catalog entry for the given track key."""
    path = show_catalog_path(track_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    stamped = {_SCHEMA_KEY: SCHEMA_VERSION, **payload}
    path.write_text(json.dumps(stamped, indent=2, sort_keys=True), encoding="utf-8")
    return path


def list_show_catalog_paths() -> list[Path]:
    """Return all persisted show catalog file paths."""
    root = show_catalog_root()
    if not root.is_dir():
        return []
    return sorted(path for path in root.glob("*.json") if path.is_file())
