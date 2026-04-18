"""Show-section resolution helpers for the showplan facade."""

from __future__ import annotations

import copy
from typing import Any, Callable

from photonic_synesthesia.showplan.types import (
    CUE_RECIPE_VERSION as _CUE_RECIPE_VERSION,
    LASER_PROGRAM_VERSION as _LASER_PROGRAM_VERSION,
    SHOW_SECTION_GENERATOR_VERSION as _SHOW_SECTION_GENERATOR_VERSION,
    clamp as _clamp,
)


def _identity_selection_mode(selection_mode: str | None) -> str:
    if selection_mode is None:
        return "procedural"
    return str(selection_mode)


def _identity_selection_variance(value: Any | None) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _identity_venue_mode(value: str | None) -> str:
    if value is None:
        return "small_room_50_100"
    return str(value)


def _default_minimal_show_sections(
    markers: list[dict[str, Any]],
    duration_seconds: float,
    *,
    track_seed: str | None = None,
    semantic_profile: dict[str, Any] | None = None,
    selection_mode: str = "procedural",
    selection_variance: float = 0.0,
    venue_mode: str = "small_room_50_100",
    metadata_confidence: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Fallback used when no CLI-backed builder is injected.

    Returns a single Auto section covering the full track duration so callers
    always receive a non-empty list. Production code always injects the real
    `_default_show_sections` builder from the CLI module.
    """
    duration = max(0.001, float(duration_seconds))
    return [
        {
            "generator_version": _SHOW_SECTION_GENERATOR_VERSION,
            "id": "section_000",
            "label": "Auto Intro",
            "kind": "intro",
            "start_seconds": 0.0,
            "end_seconds": round(duration, 3),
        }
    ]


def resolve_show_sections(
    persisted_show_plan: dict[str, Any] | None,
    markers: list[dict[str, Any]],
    duration_seconds: float,
    *,
    track_seed: str,
    semantic_profile: dict[str, Any] | None = None,
    selection_mode: str | None = None,
    selection_variance: float | None = None,
    venue_mode: str | None = None,
    metadata_confidence: dict[str, Any] | None = None,
    normalize_selection_mode: Callable[[str | None], str] | None = None,
    normalize_selection_variance: Callable[[Any | None], float] | None = None,
    normalize_venue_mode: Callable[[str | None], str] | None = None,
    default_show_sections_fn: Callable[..., list[dict[str, Any]]] | None = None,
    laser_program_version: int = _LASER_PROGRAM_VERSION,
    show_section_generator_version: int = _SHOW_SECTION_GENERATOR_VERSION,
    cue_recipe_version: int = _CUE_RECIPE_VERSION,
) -> list[dict[str, Any]]:
    """Load persisted sections when sane, otherwise rebuild a dynamic default plan."""
    _normalize_selection_mode = normalize_selection_mode or _identity_selection_mode
    _normalize_selection_variance = normalize_selection_variance or _identity_selection_variance
    _normalize_venue_mode = normalize_venue_mode or _identity_venue_mode
    _default_show_sections = default_show_sections_fn or _default_minimal_show_sections

    resolved_selection_mode = _normalize_selection_mode(
        selection_mode
        if selection_mode is not None
        else (persisted_show_plan or {}).get("selection_mode")
    )
    resolved_selection_variance = _normalize_selection_variance(
        selection_variance
        if selection_variance is not None
        else (persisted_show_plan or {}).get("selection_variance")
    )
    resolved_venue_mode = _normalize_venue_mode(
        venue_mode
        if venue_mode is not None
        else (persisted_show_plan or {}).get("venue_mode")
    )
    generated_field_names = {
        "generator_version",
        "section_role",
        "venue_mode",
        "venue_profile",
        "cue_family_id",
        "lead_family",
        "fixture_role_map",
        "transition_intent",
        "fixture_capability_graph",
        "capability_notes",
        "scene_id",
        "fixture_mode",
        "intensity_multiplier",
        "motion_multiplier",
        "strobe_level",
        "strobe_profile",
        "laser_pattern",
        "laser_variant",
        "laser_expression",
        "laser_program",
        "cue_recipe",
        "mover_pattern",
        "mover_variant",
        "wash_pattern",
        "wash_variant",
        "led_pattern",
        "led_variant",
        "laser_enabled",
        "movers_enabled",
        "washes_enabled",
        "leds_enabled",
    }

    def _laser_program_is_stale(program: Any) -> bool:
        if not isinstance(program, dict):
            return True
        if int(program.get("version", 0) or 0) != laser_program_version:
            return True
        sustain = program.get("sustain")
        fills = program.get("fills")
        launch = program.get("launch")
        release = program.get("release")
        if not isinstance(sustain, list) or not isinstance(fills, list):
            return True
        if len(sustain) != 2 or len(fills) != 2:
            return True
        if not isinstance(launch, dict) or not isinstance(release, dict):
            return True
        if str(launch.get("label", "")) != "Launch Hook":
            return True
        if str(release.get("label", "")) != "Release Hook":
            return True
        if [str(look.get("label", "")) for look in sustain] != ["Sustain A", "Sustain B"]:
            return True
        if [str(look.get("label", "")) for look in fills] != ["Fill A", "Fill B"]:
            return True
        return False

    def _generated_section_is_stale(section: dict[str, Any]) -> bool:
        if int(section.get("generator_version", 0) or 0) != show_section_generator_version:
            return True
        cue_recipe = section.get("cue_recipe")
        if not isinstance(cue_recipe, dict):
            return True
        if int(cue_recipe.get("version", 0) or 0) != cue_recipe_version:
            return True
        if not isinstance(cue_recipe.get("trigger_policy"), dict):
            return True
        return _laser_program_is_stale(section.get("laser_program"))

    fallback_sections_cache: list[dict[str, Any]] | None = None

    def _fallback_sections() -> list[dict[str, Any]]:
        nonlocal fallback_sections_cache
        if fallback_sections_cache is None:
            fallback_sections_cache = _default_show_sections(
                markers,
                duration_seconds,
                track_seed=track_seed,
                semantic_profile=semantic_profile,
                selection_mode=resolved_selection_mode,
                selection_variance=resolved_selection_variance,
                venue_mode=resolved_venue_mode,
                metadata_confidence=metadata_confidence,
            )
        return fallback_sections_cache

    if not persisted_show_plan or not isinstance(persisted_show_plan.get("show_sections"), list):
        return _fallback_sections()

    sections = [dict(section) for section in persisted_show_plan.get("show_sections", [])]
    if not sections:
        return _fallback_sections()

    sections.sort(key=lambda section: float(section.get("start_seconds", 0.0)))
    if (
        len(sections) == 1
        and str(sections[0].get("label", "")).startswith("Auto ")
    ):
        return _fallback_sections()
    if duration_seconds > 5 and max(float(section.get("end_seconds", 0.0)) for section in sections) <= 1.0:
        return _fallback_sections()

    selection_mode_mismatch = _normalize_selection_mode(
        persisted_show_plan.get("selection_mode")
    ) != resolved_selection_mode
    selection_variance_mismatch = _normalize_selection_variance(
        persisted_show_plan.get("selection_variance")
    ) != resolved_selection_variance
    venue_mode_mismatch = _normalize_venue_mode(
        persisted_show_plan.get("venue_mode")
    ) != resolved_venue_mode

    normalized: list[dict[str, Any]] = []
    duration = max(0.001, float(duration_seconds))
    for index, section in enumerate(sections):
        normalized_section = dict(section)
        try:
            start = float(normalized_section.get("start_seconds", 0.0))
        except (TypeError, ValueError):
            return _fallback_sections()
        start = _clamp(start, 0.0, duration)
        if index + 1 < len(sections):
            try:
                next_start = float(sections[index + 1].get("start_seconds", duration))
            except (TypeError, ValueError):
                next_start = duration
        else:
            next_start = duration
        next_start = _clamp(next_start, start, duration)
        try:
            raw_end = float(normalized_section.get("end_seconds", next_start))
        except (TypeError, ValueError):
            raw_end = next_start
        end = _clamp(raw_end, start, duration)
        if end <= start:
            end = next_start if next_start > start else duration
        if end <= start:
            return _fallback_sections()
        normalized_section["start_seconds"] = round(start, 3)
        normalized_section["end_seconds"] = round(end, 3)
        if (
            selection_mode_mismatch
            or selection_variance_mismatch
            or venue_mode_mismatch
            or _generated_section_is_stale(normalized_section)
        ) and index < len(_fallback_sections()):
            fallback_section = _fallback_sections()[index]
            for field_name in generated_field_names:
                normalized_section[field_name] = copy.deepcopy(fallback_section[field_name])
        normalized.append(normalized_section)

    if normalized[-1]["end_seconds"] < round(duration * 0.98, 3):
        normalized[-1]["end_seconds"] = round(duration, 3)

    return normalized
