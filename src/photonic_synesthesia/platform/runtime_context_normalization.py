"""Normalization and clamp helpers for runtime playback context."""

from __future__ import annotations

from typing import Any

PLAYBACK_SELECTION_MODES = {"procedural", "ai_assisted", "local_ollama_cpu"}
PLAYBACK_VENUE_MODES = {"small_room_50_100", "medium_room_150_400"}
PLAYBACK_OPERATOR_INTENTS = {
    "darken",
    "brighten",
    "reduce_laser_density",
    "less_strobe",
    "favor_overhead",
    "freeze_hero_family",
    "hold_current_palette",
    "delay_peak",
    "promote_washes",
}
PLAYBACK_OPERATOR_SCOPES = {"current_section", "next_phrase", "track", "set"}
PLAYBACK_OPERATOR_TARGETS = {"all", "lasers", "movers", "washes", "leds", "strobes"}


def normalize_selection_mode(selection_mode: str | None) -> str:
    value = str(selection_mode or "procedural").strip().lower().replace("-", "_")
    return value if value in PLAYBACK_SELECTION_MODES else "procedural"


def normalize_selection_variance(value: Any | None) -> float:
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return 0.0
    return round(max(0.0, min(1.0, normalized)), 3)


def normalize_metadata_source(source: str | None) -> str:
    value = str(source or "manual").strip().lower().replace("-", "_")
    return value or "manual"


def normalize_venue_mode(value: str | None) -> str:
    normalized = str(value or "small_room_50_100").strip().lower().replace("-", "_")
    return normalized if normalized in PLAYBACK_VENUE_MODES else "small_room_50_100"


def normalize_operator_intent(value: str | None) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    return normalized if normalized in PLAYBACK_OPERATOR_INTENTS else ""


def normalize_operator_scope(value: str | None) -> str:
    normalized = str(value or "track").strip().lower().replace("-", "_")
    return normalized if normalized in PLAYBACK_OPERATOR_SCOPES else "track"


def normalize_operator_target(value: str | None) -> str:
    normalized = str(value or "all").strip().lower().replace("-", "_")
    return normalized if normalized in PLAYBACK_OPERATOR_TARGETS else "all"


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
