"""Persistent storage for generated and edited show plans."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from photonic_synesthesia.core.logging import get_logger

logger = get_logger(__name__)

SCHEMA_VERSION = 2
_SCHEMA_KEY = "_schema_version"


def _migrate_show_plan_v1_to_v2(payload: dict[str, Any]) -> dict[str, Any]:
    """Add v2 fields with empty defaults and stamp the new schema version.

    Cycle-1 panel UF-2 fix: stamps the LITERAL `2`, not `SCHEMA_VERSION`,
    so a future v3 bump does not re-run this migration on valid v2 plans.
    Cycle-3 panel NC-7: persisted `operator_intents` is added at v2 — v1
    plans get an empty list (intent state was never a v1 contract).
    """
    payload.setdefault("timeline_flags", [])
    payload.setdefault("staged_look", None)
    payload.setdefault("operator_intents", [])
    payload[_SCHEMA_KEY] = 2  # literal, not SCHEMA_VERSION
    return payload


def show_plan_root() -> Path:
    """Return the user-local root directory for persisted show plans."""
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else (Path.home() / ".local" / "share")
    return base / "photonic_synesthesia" / "show_plans"


def ilda_export_root() -> Path:
    """Return the user-local root directory for generated ILDA exports."""
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else (Path.home() / ".local" / "share")
    return base / "photonic_synesthesia" / "ilda_exports"


def _legacy_sanitize_show_plan_key(value: str) -> str:
    """Normalize a track key into a filesystem-safe stem."""
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in value.strip())
    compact = "_".join(segment for segment in cleaned.split("_") if segment)
    return compact or "unknown_track"


def sanitize_show_plan_key(value: str) -> str:
    """Normalize a track key into a filesystem-safe, collision-resistant stem."""
    legacy = _legacy_sanitize_show_plan_key(value)
    digest = hashlib.sha1(value.strip().encode("utf-8")).hexdigest()[:12]
    return f"{legacy}__{digest}"


def show_plan_path(track_key: str) -> Path:
    """Return the JSON path for a persisted show plan."""
    return show_plan_root() / f"{sanitize_show_plan_key(track_key)}.json"


def ilda_export_path(track_key: str) -> Path:
    """Return the `.ild` path for a generated ILDA export."""
    return ilda_export_root() / f"{sanitize_show_plan_key(track_key)}.ild"


def _legacy_show_plan_path(track_key: str) -> Path:
    return show_plan_root() / f"{_legacy_sanitize_show_plan_key(track_key)}.json"


def load_show_plan(track_key: str) -> dict[str, Any] | None:
    """Load a persisted show plan for the given track key.

    Tolerates the legacy filename scheme (`_legacy_show_plan_path`) and the
    current collision-resistant scheme. Returns None on missing, malformed,
    or non-object JSON payloads (logged at warning level).
    """
    path = show_plan_path(track_key)
    if not path.is_file():
        path = _legacy_show_plan_path(track_key)
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("show_plan load failed", path=str(path), error=str(exc))
        return None
    if not isinstance(payload, dict):
        logger.warning(
            "show_plan payload is not a JSON object",
            path=str(path),
            type=type(payload).__name__,
        )
        return None
    stored_version = payload.get(_SCHEMA_KEY)
    if isinstance(stored_version, int) and stored_version > SCHEMA_VERSION:
        logger.warning(
            "show_plan schema is newer than this build",
            path=str(path),
            stored=stored_version,
            local=SCHEMA_VERSION,
        )
    # v1→v2 migration. Use literal `== 1` (cycle-1 panel UF-2): a future v3
    # bump adds its own `elif version == 2:` branch; this gate cannot
    # accidentally re-fire on valid v2 plans.
    version = int(payload.get(_SCHEMA_KEY, 1) or 1)
    if version == 1:
        payload = _migrate_show_plan_v1_to_v2(payload)
    return payload


def save_show_plan(track_key: str, payload: dict[str, Any]) -> Path:
    """Persist a show plan JSON payload for the given track key.

    Atomic-write contract (cycle-1 panel SF-2): writes to a `.tmp` sibling
    in the same directory, then `os.replace`s into place. On failure, the
    temp file is removed and the previous payload (if any) remains intact.
    Atomic on POSIX and on Windows NTFS for files in the same directory.
    """
    path = show_plan_path(track_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    stamped = {_SCHEMA_KEY: SCHEMA_VERSION, **payload}
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(stamped, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise
    return path
