"""Shared typed aliases, helpers, and version constants for showplan modules.

This module is the single source of truth for small utilities and version
numbers that used to be duplicated across `cli.py` and individual
`showplan/*.py` leaves during the extraction slices. Other showplan modules
(and `cli.py`) import from here rather than re-defining their own copies.

No Click, no runtime/UI imports — this module is allowed to be imported by
both sides of the CLI / showplan boundary.
"""

from __future__ import annotations

from typing import Any, TypeAlias, TypedDict

ShowSection: TypeAlias = dict[str, Any]
StructureMarker: TypeAlias = dict[str, Any]
SemanticProfile: TypeAlias = dict[str, Any]
ModelPayload: TypeAlias = dict[str, Any]


# --- Professional rollout authored types (Task 1) ---------------------------

class TimelineFlag(TypedDict, total=False):
    id: str
    kind: str
    at_seconds: float
    payload: dict[str, Any]


class LaserZoneRule(TypedDict, total=False):
    zone_id: str
    mode: str
    brightness_cap: float
    protected: bool
    allow_position_fx: bool


class StagedLook(TypedDict, total=False):
    id: str
    source: str
    section_id: str
    cue_recipe: dict[str, Any]
    laser_program: dict[str, Any]
    committed: bool


# Single authoritative safety-mode list (cycle-1 panel UF-29 fix). All
# consumers (workspace builder, _ZONE_POLICY_RULES, recipe bundle) import
# from here. Tuple, not list, so no consumer can mutate it in place.
SAFETY_MODES: tuple[str, ...] = (
    "overhead_only",
    "overhead_bias",
    "mixed_air",
    "crowd_punctuate",
    "laser_off",
    "balanced",
)

# --- Version constants ------------------------------------------------------
# Owned here; CLI and showplan leaves import from this module.
LASER_PROGRAM_VERSION = 3
SHOW_SECTION_GENERATOR_VERSION = 7
SEMANTIC_PROFILE_VERSION = 1
CUE_RECIPE_VERSION = 6
CATALOG_VERSION = 7

# --- Domain constants -------------------------------------------------------
VENUE_MODES: frozenset[str] = frozenset({"small_room_50_100", "medium_room_150_400"})
SELECTION_MODES: frozenset[str] = frozenset({"procedural", "ai_assisted", "local_ollama_cpu"})


# --- Shared numeric helpers -------------------------------------------------
def clamp(value: float, minimum: float, maximum: float) -> float:
    """Clamp `value` into the inclusive `[minimum, maximum]` range."""
    return max(minimum, min(maximum, value))


def safe_confidence_value(raw: Any, default: float = 0.0) -> float:
    """Coerce arbitrary input into a rounded confidence value in [0, 1]."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = default
    return round(clamp(value, 0.0, 1.0), 3)


# --- Venue / zone helpers ---------------------------------------------------
def normalize_venue_mode(value: str | None) -> str:
    """Normalize a venue mode string; fall back to the small-room default."""
    normalized = str(value or "small_room_50_100").strip().lower().replace("-", "_")
    return normalized if normalized in VENUE_MODES else "small_room_50_100"


def normalize_selection_mode(selection_mode: str | None) -> str:
    """Normalize a selection-mode string; fall back to procedural."""
    value = str(selection_mode or "procedural").strip().lower().replace("-", "_")
    return value if value in SELECTION_MODES else "procedural"


def normalize_selection_variance(value: Any | None) -> float:
    """Coerce variance input to a float in [0, 1], rounded to 3dp."""
    if value is None:
        return 0.0
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return 0.0
    return round(clamp(normalized, 0.0, 1.0), 3)


def apply_venue_laser_zone_policy(venue_mode: str, zone_policy: str) -> str:
    """Tighten a laser zone policy for a given venue class."""
    venue = normalize_venue_mode(venue_mode)
    if venue == "small_room_50_100":
        return "overhead_only"
    if zone_policy == "crowd_punctuate":
        return "overhead_bias"
    return zone_policy


def cue_family_id(section_role: str, lead_family: str, venue_mode: str) -> str:
    """Stable cue family identifier keyed on venue/role/lead-family."""
    return f"{normalize_venue_mode(venue_mode)}::{section_role}::{lead_family}"


# --- Pattern-stage helpers --------------------------------------------------
def pattern_stage(kind: str) -> str:
    """Map a marker kind to its high-level stage label."""
    if kind == "drop":
        return "drop"
    if kind == "build":
        return "build"
    if kind in {"breakdown", "bridge", "verse", "vocal"}:
        return "breakdown"
    if kind == "outro":
        return "outro"
    return "intro"


def laser_zone_policy(kind: str, context: str) -> str:
    """Choose the laser zone policy for a section's stage/context combo."""
    stage = pattern_stage(kind)
    if stage == "breakdown":
        return "overhead_only"
    if context == "drop_launch":
        return "crowd_punctuate"
    if stage == "build":
        return "mixed_air"
    if stage == "drop":
        return "mixed_air"
    return "overhead_bias"
