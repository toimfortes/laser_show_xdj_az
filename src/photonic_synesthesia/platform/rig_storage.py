"""Persistent storage for named "rig" presets ("Antonio's Lights", etc.).

Two responsibilities:

1. **Phase A — persist canvas layouts.** A rig is a named JSON file containing
   the user's `MockRigStore` fixtures (positions, colors, addresses, profile
   bindings). Stored under XDG_DATA_HOME with one file per rig and an
   `_active.json` pointer indicating which rig should hydrate the canvas on
   startup.

2. **Phase B — drive the runtime graph.** `materialize_to_fixture_configs()`
   converts a saved rig into a list of `FixtureConfig` instances suitable for
   `Settings.fixtures`, so the runtime DMX/ILDA path actually uses the user's
   patch rather than a hand-edited YAML.

Schema versioning mirrors `integrations/show_plans.py`. Atomic writes use
`tmp + os.replace` (POSIX-atomic; same-directory NTFS-atomic).
"""

from __future__ import annotations

import copy
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from photonic_synesthesia.core.config import FixtureConfig
from photonic_synesthesia.core.logging import get_logger

logger = get_logger(__name__)

RIG_SCHEMA_VERSION = 1
_SCHEMA_KEY = "_schema_version"

# Cycle-1 panel H1 (3/4 convergent: Codex + Claude + Kilo): the regex MUST
# require a leading alphanumeric so names like `-` or `_anything` are rejected
# at the storage boundary, AND the reserved-name denylist MUST forbid sentinel
# stems that share the on-disk filename namespace with control files (today
# `_active.json`; future control files MUST be added here when introduced).
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_RESERVED_NAMES = frozenset({"_active", "_schema_version"})

# Default profile mapping for rig fixtures created from canvas templates.
# Only types with a runtime DMX profile YAML get a default; visual-only
# templates (moving_head, wash, panel, led_bar) get None and must be
# manually assigned a profile by the user before they materialize.
DEFAULT_PROFILE_BY_TYPE: dict[str, str | None] = {
    "laser": "laser_generic_9ch",
    "moving_head": None,
    "wash": None,
    "panel": None,
    "led_bar": None,
}


class RigBridgeError(RuntimeError):
    """Raised by Phase B materialization on unrecoverable rig errors.

    Examples: address conflicts that the user MUST resolve, structural
    schema violations that prevent any materialization. Recoverable
    failures (missing profile YAML on one fixture, Pydantic validation
    error on one fixture) are surfaced via the `warnings` return tuple
    instead, so a partially-broken rig still boots with the rest of
    its fixtures.
    """


@dataclass(frozen=True)
class Conflict:
    """One DMX address conflict between two fixtures."""

    universe: int
    channel: int
    fixture_a_id: str
    fixture_b_id: str

    def describe(self) -> str:
        return (
            f"universe {self.universe} channel {self.channel}: "
            f"{self.fixture_a_id} overlaps with {self.fixture_b_id}"
        )


# ---------------------------------------------------------------------------
# Path resolution


def _xdg_data_home() -> Path:
    """Return XDG_DATA_HOME (or its default `~/.local/share`)."""
    xdg = os.environ.get("XDG_DATA_HOME")
    return Path(xdg) if xdg else (Path.home() / ".local" / "share")


def rigs_root() -> Path:
    """Directory holding all saved rig files + the `_active.json` pointer.

    Always returns the current value (re-reads `XDG_DATA_HOME` on every
    call) so tests can monkeypatch the env var per-test without import-time
    caching getting in the way.
    """
    return _xdg_data_home() / "photonic_synesthesia" / "rigs"


def rig_path(name: str) -> Path:
    """Return the JSON path for a saved rig with the given name.

    Caller is responsible for `_validate_name(name)` first; this function
    does NOT validate (so internal callers can use it for both legitimate
    rig names AND control filenames if needed in future).
    """
    return rigs_root() / f"{name}.json"


def _active_pointer_path() -> Path:
    return rigs_root() / "_active.json"


# ---------------------------------------------------------------------------
# Name validation


def _validate_name(name: str) -> None:
    """Raise ValueError if name is reserved or fails the regex.

    Reserved sentinels (`_active`, `_schema_version`) are rejected even
    though they pass the regex's leading-char rule (they don't — they
    start with `_`), because they share the on-disk filename namespace
    with control files. The denylist is enforced explicitly so future
    additions to the reserved set are obvious.
    """
    if not isinstance(name, str):
        raise ValueError(f"rig name must be str, got {type(name).__name__}")
    if name in _RESERVED_NAMES:
        raise ValueError(f"rig name {name!r} is reserved")
    if not _NAME_RE.match(name):
        raise ValueError(
            f"rig name {name!r} must match {_NAME_RE.pattern!r} "
            "(lowercase alphanumeric/underscore/dash, leading char must be alphanumeric)"
        )


# ---------------------------------------------------------------------------
# Atomic write helper (mirrors show_plans.py:128-138)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def _now_iso_utc_z() -> str:
    """Return current UTC time as ISO 8601 with literal Z suffix.

    Cycle-1 panel L3 (Claude): `saved_at` MUST be tz-aware UTC with the
    `Z` suffix so consumers can parse without ambiguity. Mirrors the
    in-repo show_plans convention.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Save / load / list / delete


def _strip_server_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with server-stamped fields removed.

    Cycle-1 panel A10 (Claude M1 + Kilo M1): `_schema_version` and
    `saved_at` are server-stamped on save. The PUT endpoint MUST strip
    them from client input so a client that GETs and re-PUTs cannot
    forge `saved_at` or downgrade the schema version.
    """
    cleaned = dict(payload)
    cleaned.pop(_SCHEMA_KEY, None)
    cleaned.pop("saved_at", None)
    return cleaned


def _validate_type_profile_invariant(fixtures: list[dict[str, Any]]) -> None:
    """Cycle-1 panel application of A13: enabled lasers MUST have a profile.

    A laser fixture without a profile is meaningless at the runtime
    layer (the materializer would skip it silently). Reject at save
    time so the user gets immediate feedback.
    """
    for fixture in fixtures:
        ftype = fixture.get("type")
        enabled = fixture.get("enabled", True)
        profile = fixture.get("profile")
        if ftype == "laser" and enabled and not profile:
            raise ValueError(
                f"fixture {fixture.get('id')!r} (type=laser, enabled=true) "
                "MUST have a non-null profile; got null. Disable the fixture, "
                "change its type, or assign a profile."
            )


def _validate_unique_ids(fixtures: list[dict[str, Any]]) -> None:
    """Cycle-1 panel M5 (Claude): reject duplicate IDs at the save boundary."""
    seen: set[str] = set()
    for fixture in fixtures:
        fid = fixture.get("id")
        if not isinstance(fid, str) or not fid:
            raise ValueError(f"fixture must have a non-empty string `id`; got {fid!r}")
        if fid in seen:
            raise ValueError(f"duplicate fixture id {fid!r} in rig payload")
        seen.add(fid)


def save_rig(name: str, fixtures: list[dict[str, Any]]) -> Path:
    """Persist a rig under the given name, server-stamping schema + timestamp.

    Cycle-1 panel C1 + H1: validates name BEFORE touching the filesystem.
    Cycle-1 panel A10: strips client-supplied schema_version / saved_at.
    Cycle-1 panel A13: enforces type-profile invariant.
    Cycle-1 panel M5: enforces unique fixture IDs.

    Returns the saved path on success. Raises ValueError on validation
    failure (no file written). Atomic on POSIX/NTFS-same-dir.
    """
    _validate_name(name)
    _validate_unique_ids(fixtures)
    _validate_type_profile_invariant(fixtures)
    payload = {
        _SCHEMA_KEY: RIG_SCHEMA_VERSION,
        "name": name,
        "saved_at": _now_iso_utc_z(),
        "fixtures": copy.deepcopy(fixtures),
    }
    path = rig_path(name)
    _atomic_write_json(path, payload)
    return path


def load_rig(name: str) -> dict[str, Any]:
    """Load a saved rig by name.

    Raises:
        FileNotFoundError: if the rig file does not exist.
        ValueError: if the file is malformed JSON, is not a JSON object,
            or has a `_schema_version` newer than this build supports.
    """
    _validate_name(name)
    path = rig_path(name)
    if not path.is_file():
        raise FileNotFoundError(f"rig {name!r} does not exist at {path}")
    raw = path.read_text(encoding="utf-8")
    payload = json.loads(raw)  # raises json.JSONDecodeError (subclass of ValueError)
    if not isinstance(payload, dict):
        raise ValueError(f"rig {name!r} payload is not a JSON object")

    # Cycle-1 panel H2 (3/4 convergent: Codex + Claude + Kilo) — the A8 trap.
    # The legacy fallback for the missing version key MUST be the literal `1`,
    # NOT `RIG_SCHEMA_VERSION`. If a future v2 lands, files written under v1
    # without a schema key (somehow — they shouldn't exist, but defensive)
    # must be interpreted as v1 and migrated, not silently re-stamped as v2.
    # Mirrors show_plans.py:109-111. Pinned by
    # test_load_rig_missing_schema_key_treated_as_v1_even_after_constant_bump.
    version = int(payload.get(_SCHEMA_KEY, 1) or 1)
    if version > RIG_SCHEMA_VERSION:
        raise ValueError(
            f"rig {name!r} schema version {version} is newer than this build "
            f"({RIG_SCHEMA_VERSION}); refusing to load"
        )
    # No migrations exist yet (v1 is the only version). When v2 lands, add an
    # `if version == 1:` branch here that calls `_migrate_v1_to_v2(payload)`.

    if not isinstance(payload.get("fixtures"), list):
        raise ValueError(f"rig {name!r} missing or invalid `fixtures` list")
    return payload


def list_rigs() -> list[dict[str, Any]]:
    """Return metadata stubs for every saved rig.

    Total function: never raises; returns [] if the rigs directory does
    not yet exist or any individual file is corrupt (corrupt files are
    skipped with a warning log).
    """
    root = rigs_root()
    if not root.is_dir():
        return []
    items: list[dict[str, Any]] = []
    active = get_active_rig_name()
    for entry in sorted(root.glob("*.json")):
        if entry.name.startswith("_"):
            continue  # control files (e.g. _active.json)
        name = entry.stem
        try:
            payload = json.loads(entry.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("rig list: skipping corrupt file", path=str(entry), error=str(exc))
            continue
        if not isinstance(payload, dict):
            continue
        items.append(
            {
                "name": name,
                "fixture_count": len(payload.get("fixtures", []) or []),
                "saved_at": payload.get("saved_at"),
                "is_active": name == active,
            }
        )
    items.sort(key=lambda item: item.get("saved_at") or "", reverse=True)
    return items


def delete_rig(name: str, *, force: bool = False) -> bool:
    """Delete the named rig file.

    Cycle-1 panel Kilo H2 + Claude H1: if `name` is the active rig, the
    default behavior REFUSES the delete (returns False) so a stale
    `_active.json` pointer cannot be left behind. With `force=True`,
    the active pointer is atomically cleared FIRST, then the rig file
    is removed. If the pointer-clear succeeds but the unlink fails, the
    pointer stays cleared (consistent: no rig is active and the rig
    file may or may not exist; safer than the inverse).

    Returns True if the file was removed, False if it did not exist or
    the delete was refused.
    """
    _validate_name(name)
    path = rig_path(name)
    if not path.is_file():
        return False
    active = get_active_rig_name()
    if name == active and not force:
        return False
    if name == active and force:
        # Clear the pointer FIRST so a crash between this and the unlink
        # leaves us with "no active rig" rather than "active rig points
        # at a missing file" (the latter would re-trip the get_active_rig_name
        # auto-clear path on next startup; harmless but noisier).
        set_active_rig(None)
    path.unlink()
    return True


def set_active_rig(name: str | None) -> None:
    """Set (or clear with `name=None`) the active rig pointer.

    Cycle-1 panel Claude L2: when setting (not clearing), validates that
    the target rig file exists. Raises FileNotFoundError otherwise so
    callers can't create a dangling pointer.
    """
    if name is not None:
        _validate_name(name)
        if not rig_path(name).is_file():
            raise FileNotFoundError(
                f"cannot activate rig {name!r}: file does not exist"
            )
    payload = {"active": name, "updated_at": _now_iso_utc_z()}
    _atomic_write_json(_active_pointer_path(), payload)


def get_active_rig_name() -> str | None:
    """Return the active rig name, OR None if there is no active rig OR
    the pointer is stale (auto-clearing in the latter case).

    Cycle-1 panel C1 (3/4 convergent: Codex CRITICAL + Gemini CRITICAL +
    Claude HIGH#1): a stale pointer (file deleted out-of-band) MUST NOT
    crash startup. We treat `_active.json` as ADVISORY: if it points at
    a missing file, we clear it to null (with a WARN log) and return
    None so the caller falls back to defaults. The next startup sees a
    clean state.
    """
    pointer = _active_pointer_path()
    if not pointer.is_file():
        return None
    try:
        payload = json.loads(pointer.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "active rig pointer is corrupt; clearing", path=str(pointer), error=str(exc)
        )
        try:
            _atomic_write_json(pointer, {"active": None, "updated_at": _now_iso_utc_z()})
        except OSError:
            pass
        return None
    if not isinstance(payload, dict):
        return None
    name = payload.get("active")
    if name is None:
        return None
    if not isinstance(name, str):
        return None
    # Stale pointer: file deleted out-of-band.
    if not rig_path(name).is_file():
        logger.warning(
            "active rig pointer is stale; clearing",
            name=name,
            expected_path=str(rig_path(name)),
        )
        try:
            _atomic_write_json(pointer, {"active": None, "updated_at": _now_iso_utc_z()})
        except OSError:
            pass
        return None
    return name


# ---------------------------------------------------------------------------
# Profile YAML helpers


def list_available_profiles(fixtures_dir: Path) -> list[dict[str, Any]]:
    """List every fixture profile YAML in `fixtures_dir`.

    Returns metadata stubs for the UI dropdown:
        [{slug, name, type, channels}, ...]

    Total function: returns [] if the directory is missing or empty.
    Profiles without a top-level `channels` key (e.g. ILDA-hybrid like
    `laser_aucd_cx338b_hybrid`) report `channels: None`; UI shows
    "(ILDA / hybrid)" in that case.
    """
    if not fixtures_dir.is_dir():
        return []
    profiles: list[dict[str, Any]] = []
    for entry in sorted(fixtures_dir.glob("*.yaml")):
        try:
            payload = yaml.safe_load(entry.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            logger.warning(
                "fixture profile load failed", path=str(entry), error=str(exc)
            )
            continue
        if not isinstance(payload, dict):
            continue
        profiles.append(
            {
                "slug": entry.stem,
                "name": payload.get("name") or entry.stem,
                "type": payload.get("type") or "unknown",
                "channels": payload.get("channels"),
            }
        )
    return profiles


def _read_profile_channels(profile_slug: str, fixtures_dir: Path) -> int | None:
    """Read the DMX channel count for a profile, following the
    `dmx_adapter_profile` chain for hybrid profiles.

    Cycle-1 panel Kilo H6 (verified against
    `config/fixtures/laser_aucd_cx338b_hybrid.yaml:11`): the hybrid
    profile has no top-level `channels` field; it defers to
    `dmx_adapter_profile: laser_generic_9ch`. We MUST follow the chain
    or address-conflict detection silently skips the fixture.

    Returns:
        - integer channel count if the profile (or the chain target)
          has a `channels` field
        - None if the profile is missing, malformed, or the chain
          terminates without a `channels` field

    Never raises. Callers treat None as "skip this fixture for conflict
    detection but materialize anyway" (a warning is logged).
    """
    visited: set[str] = set()
    current = profile_slug
    while current and current not in visited:
        visited.add(current)
        path = fixtures_dir / f"{current}.yaml"
        if not path.is_file():
            return None
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            return None
        if not isinstance(payload, dict):
            return None
        channels = payload.get("channels")
        if isinstance(channels, int) and channels > 0:
            return channels
        chain = payload.get("dmx_adapter_profile")
        if not isinstance(chain, str) or not chain:
            return None
        current = chain
    return None


# ---------------------------------------------------------------------------
# Phase B: runtime bridge


def detect_address_conflicts(
    fixtures: list[dict[str, Any]],
    fixtures_dir: Path,
) -> list[Conflict]:
    """Detect overlapping DMX channel ranges across enabled fixtures.

    Total function — never raises. Returns [] if `fixtures_dir` is
    missing, if no fixtures have a profile, or if all profiles fail to
    resolve a channel count.

    Cycle-1 panel Kilo H6: handles the `dmx_adapter_profile` chain via
    `_read_profile_channels`. Cycle-1 panel Codex M2/H#3: the caller
    threads in the runtime's effective fixtures_dir so this matches
    what the graph actually loads.
    """
    if not fixtures_dir.is_dir():
        return []
    # Build (universe, channel) → first-fixture-id map.
    occupied: dict[tuple[int, int], str] = {}
    conflicts: list[Conflict] = []
    for fixture in fixtures:
        if not fixture.get("enabled", True):
            continue
        profile = fixture.get("profile")
        if not isinstance(profile, str) or not profile:
            continue
        channels = _read_profile_channels(profile, fixtures_dir)
        if channels is None:
            continue
        try:
            universe = int(fixture.get("universe", 1))
            start = int(fixture.get("address", 1))
        except (TypeError, ValueError):
            continue
        for offset in range(channels):
            ch = start + offset
            if ch > 512:
                break
            key = (universe, ch)
            other = occupied.get(key)
            if other is not None and other != fixture.get("id"):
                conflicts.append(
                    Conflict(
                        universe=universe,
                        channel=ch,
                        fixture_a_id=other,
                        fixture_b_id=str(fixture.get("id", "<unknown>")),
                    )
                )
            else:
                occupied[key] = str(fixture.get("id", "<unknown>"))
    return conflicts


def materialize_to_fixture_configs(
    rig: dict[str, Any],
    fixtures_dir: Path,
) -> tuple[list[FixtureConfig], list[str]]:
    """Convert a saved rig dict into a list of `FixtureConfig` instances.

    Returns `(configs, warnings)`. Per fixture:
      - if `enabled is False`: skip silently.
      - if `profile is None`: skip silently (visual-only).
      - if profile YAML referenced but missing: skip with a warning string
        (closes cycle-1 panel H3 — Gemini + Claude + Kilo).
      - if construction fails Pydantic validation: skip with warning.

    Cycle-1 panel C2 (Kilo CRITICAL, verified `core/config.py:91`):
    `FixtureConfig.profile: str` is REQUIRED with no `| None`. Null-profile
    filtering MUST happen BEFORE FixtureConfig construction or pydantic
    raises ValidationError. The plan's invariant is enforced explicitly.

    Cycle-1 panel H4 (Gemini + Claude + Kilo): the CALLER decides what to
    do with an empty result — this function does not impose policy. CLI
    bridge logic (Phase B) checks `rig["fixtures"]` length vs the
    materialized list to distinguish "rig has no fixtures" from "rig has
    fixtures but none are runtime-eligible" and emit different messages.

    After per-fixture filtering, runs `detect_address_conflicts` on the
    surviving entries; if conflicts exist, raises `RigBridgeError` with
    every conflict named (the user MUST resolve those — silent
    materialization with overlapping channels would corrupt DMX output).
    """
    if not isinstance(rig, dict):
        raise RigBridgeError("rig payload must be a dict")
    fixtures = rig.get("fixtures") or []
    if not isinstance(fixtures, list):
        raise RigBridgeError("rig payload `fixtures` must be a list")

    configs: list[FixtureConfig] = []
    warnings: list[str] = []
    surviving_for_conflict_check: list[dict[str, Any]] = []

    for fixture in fixtures:
        fid = str(fixture.get("id", "<unknown>"))
        if not fixture.get("enabled", True):
            continue
        profile = fixture.get("profile")
        # Cycle-1 panel C2 — null filter BEFORE FixtureConfig construction.
        if not isinstance(profile, str) or not profile:
            continue
        # Verify the profile YAML actually exists before constructing the config
        # so we get a clean warning rather than a confusing graph-build error
        # later (closes Gemini H + Claude H + Kilo H).
        if not (fixtures_dir / f"{profile}.yaml").is_file():
            warnings.append(
                f"fixture {fid!r} references profile {profile!r} which is missing "
                f"from {fixtures_dir}; fixture will not be materialized"
            )
            continue
        try:
            config = FixtureConfig(
                id=fid,
                name=str(fixture.get("label") or fid),
                type=str(fixture.get("type", "laser")),
                profile=profile,
                start_address=int(fixture.get("address", 1)),
                enabled=True,
            )
        except Exception as exc:  # pragma: no cover - pydantic validation surface
            warnings.append(
                f"fixture {fid!r} failed FixtureConfig validation ({exc}); "
                "fixture will not be materialized"
            )
            continue
        configs.append(config)
        surviving_for_conflict_check.append(fixture)

    conflicts = detect_address_conflicts(surviving_for_conflict_check, fixtures_dir)
    if conflicts:
        descriptions = "\n  - ".join(c.describe() for c in conflicts)
        raise RigBridgeError(
            f"rig has {len(conflicts)} DMX address conflict(s):\n  - {descriptions}\n"
            "Resolve in the web UI before activating this rig."
        )
    return configs, warnings


__all__ = [
    "Conflict",
    "DEFAULT_PROFILE_BY_TYPE",
    "RIG_SCHEMA_VERSION",
    "RigBridgeError",
    "_strip_server_fields",
    "_validate_name",
    "delete_rig",
    "detect_address_conflicts",
    "get_active_rig_name",
    "list_available_profiles",
    "list_rigs",
    "load_rig",
    "materialize_to_fixture_configs",
    "rig_path",
    "rigs_root",
    "save_rig",
    "set_active_rig",
]
