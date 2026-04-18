"""Show-section resolution helpers for the showplan facade."""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

from photonic_synesthesia.showplan.types import (
    CUE_RECIPE_VERSION as _CUE_RECIPE_VERSION,
)
from photonic_synesthesia.showplan.types import (
    LASER_PROGRAM_VERSION as _LASER_PROGRAM_VERSION,
)
from photonic_synesthesia.showplan.types import (
    SHOW_SECTION_GENERATOR_VERSION as _SHOW_SECTION_GENERATOR_VERSION,
)
from photonic_synesthesia.showplan.types import (
    clamp as _clamp,
)
from photonic_synesthesia.showplan.types import (
    normalize_venue_mode as _normalize_venue_mode_fn,
)
from photonic_synesthesia.showplan.types import (
    pattern_stage as _pattern_stage,
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


def transition_context(
    *,
    previous_kind: str | None,
    kind: str,
    next_kind: str | None,
    ordinal: int,
    total_of_kind: int,
) -> str:
    stage = _pattern_stage(kind)
    if stage == "drop":
        if previous_kind in {"build", "breakdown", "bridge", "verse", "vocal"}:
            return "drop_launch" if ordinal == 0 else "drop_variation"
        if ordinal > 0 or total_of_kind > 1:
            return "drop_variation"
        return "drop_launch"
    if stage == "build":
        if next_kind == "drop":
            return "build_riser"
        return "build_cycle"
    if stage == "breakdown":
        return "breakdown_release"
    if stage == "outro":
        return "outro_release"
    return "intro_set"


def normalize_section_role(
    *,
    kind: str,
    marker_name: str,
    context: str,
    ordinal: int,
    total_of_kind: int,
) -> str:
    marker_text = marker_name.strip().lower()
    if kind == "vocal" or "vocal" in marker_text:
        return "vocal"
    if kind in {"verse", "groove", "chorus"} or any(token in marker_text for token in ("verse", "groove", "chorus")):
        return "groove"
    if kind == "bridge" or "bridge" in marker_text:
        return "bridge"
    if kind == "build":
        if ordinal > 0 or context == "build_cycle":
            return "build_2"
        return "build_1"
    if kind == "drop":
        return "drop_variation" if ordinal > 0 or context == "drop_variation" else "drop_1"
    if kind == "breakdown":
        return "breakdown"
    if kind == "outro":
        return "outro"
    return "intro"


def transition_intent(
    *,
    section_role: str,
    context: str,
    previous_role: str | None,
    next_role: str | None,
) -> dict[str, Any]:
    if section_role in {"drop_1", "drop_variation"}:
        return {
            "type": "bloom" if context == "drop_launch" else "inversion",
            "duration_domain": "phrase",
            "carry_over_families": ["wash", "led"],
            "blackout_policy": "pre_drop_snap" if previous_role in {"build_1", "build_2"} else "none",
            "palette_carry": section_role == "drop_variation",
            "geometry_carry": section_role == "drop_variation",
        }
    if section_role in {"build_1", "build_2"}:
        return {
            "type": "handoff" if next_role in {"drop_1", "drop_variation"} else "develop",
            "duration_domain": "phrase",
            "carry_over_families": ["mover", "wash"],
            "blackout_policy": "none",
            "palette_carry": True,
            "geometry_carry": section_role == "build_2",
        }
    if section_role == "breakdown":
        return {
            "type": "suckout",
            "duration_domain": "phrase",
            "carry_over_families": ["wash"],
            "blackout_policy": "drop_residue_off",
            "palette_carry": False,
            "geometry_carry": False,
        }
    if section_role == "bridge":
        return {
            "type": "handoff",
            "duration_domain": "bar",
            "carry_over_families": ["led", "wash"],
            "blackout_policy": "none",
            "palette_carry": False,
            "geometry_carry": False,
        }
    if section_role == "vocal":
        return {
            "type": "dissolve",
            "duration_domain": "bar",
            "carry_over_families": ["wash"],
            "blackout_policy": "none",
            "palette_carry": True,
            "geometry_carry": False,
        }
    if section_role == "outro":
        return {
            "type": "dissolve",
            "duration_domain": "phrase",
            "carry_over_families": ["wash", "led"],
            "blackout_policy": "none",
            "palette_carry": True,
            "geometry_carry": False,
        }
    return {
        "type": "set" if previous_role is None else "handoff",
        "duration_domain": "phrase",
        "carry_over_families": ["wash"],
        "blackout_policy": "none",
        "palette_carry": previous_role == "intro",
        "geometry_carry": False,
    }


def _lead_family_for_section_role(
    *,
    section_role: str,
    venue_mode: str,
    laser_enabled: bool,
    leds_enabled: bool,
) -> str:
    venue = _normalize_venue_mode_fn(venue_mode)
    if section_role in {"intro", "vocal", "breakdown", "outro"}:
        return "wash"
    if section_role == "bridge":
        return "led" if leds_enabled else "wash"
    if section_role in {"build_1", "build_2", "groove"}:
        return "mover"
    if section_role == "drop_variation":
        if venue == "medium_room_150_400" and laser_enabled:
            return "laser"
        return "led" if leds_enabled else "mover"
    if section_role == "drop_1":
        if venue == "medium_room_150_400" and laser_enabled:
            return "laser"
        return "mover"
    return "wash"


def fixture_role_map(
    *,
    section_role: str,
    venue_mode: str,
    laser_enabled: bool,
    movers_enabled: bool,
    washes_enabled: bool,
    leds_enabled: bool,
    preferred_lead_family: str | None = None,
) -> tuple[str, dict[str, dict[str, Any]]]:
    lead_family = _lead_family_for_section_role(
        section_role=section_role,
        venue_mode=venue_mode,
        laser_enabled=laser_enabled,
        leds_enabled=leds_enabled,
    )
    family_enabled = {
        "laser": laser_enabled,
        "mover": movers_enabled,
        "wash": washes_enabled,
        "led": leds_enabled,
    }
    if preferred_lead_family in family_enabled and family_enabled[str(preferred_lead_family)]:
        lead_family = str(preferred_lead_family)
    base_roles: dict[str, str] = {
        "laser": "support",
        "mover": "support",
        "wash": "architectural",
        "led": "texture",
    }
    if section_role in {"intro", "outro"}:
        base_roles.update({"wash": "hero", "mover": "architectural", "laser": "off", "led": "texture"})
    elif section_role == "vocal":
        base_roles.update({"wash": "hero", "mover": "support", "laser": "off", "led": "texture"})
    elif section_role == "bridge":
        base_roles.update({"led": "hero", "wash": "support", "mover": "architectural", "laser": "off"})
    elif section_role in {"build_1", "build_2"}:
        base_roles.update({"mover": "hero", "wash": "support", "led": "accent", "laser": "support"})
    elif section_role == "breakdown":
        base_roles.update({"wash": "hero", "mover": "architectural", "led": "texture", "laser": "off"})
    elif section_role == "drop_1":
        base_roles.update({"wash": "support", "mover": "hero", "led": "accent", "laser": "support"})
    elif section_role == "drop_variation":
        base_roles.update({"wash": "support", "mover": "support", "led": "hero", "laser": "support"})
    else:
        base_roles.update({"mover": "hero", "wash": "architectural", "led": "texture", "laser": "support"})

    base_roles[lead_family] = "hero"
    for family, role in list(base_roles.items()):
        if family != lead_family and role == "hero":
            base_roles[family] = "support"
    role_map: dict[str, dict[str, Any]] = {}
    for family in ("laser", "mover", "wash", "led"):
        enabled = family_enabled[family]
        role = base_roles[family] if enabled else "off"
        if family == "laser":
            coupling_mode = "widen" if lead_family == "mover" else "mirror"
        elif family == "mover":
            coupling_mode = "mirror" if lead_family == "laser" else "independent"
        elif family == "wash":
            coupling_mode = "widen"
        else:
            coupling_mode = "offset"
        role_map[family] = {
            "role": role,
            "coupling_mode": coupling_mode,
            "intensity_ceiling": 1.0 if role == "hero" else (0.72 if role == "support" else 0.5),
        }
    return lead_family, role_map
