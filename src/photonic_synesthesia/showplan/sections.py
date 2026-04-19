"""Show-section resolution helpers for the showplan facade."""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

from photonic_synesthesia.core.exceptions import ShowplanError
from photonic_synesthesia.showplan._patterns import (
    LASER_PATTERN_GEOMETRY as _LASER_PATTERN_GEOMETRY,
)
from photonic_synesthesia.showplan._patterns import (
    pattern_candidates as _pattern_candidates,
)
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
    apply_venue_laser_zone_policy as _apply_venue_laser_zone_policy,
)
from photonic_synesthesia.showplan.types import (
    clamp as _clamp,
)
from photonic_synesthesia.showplan.types import (
    laser_zone_policy as _laser_zone_policy,
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


def _single_auto_intro_fallback(
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
    """Demo-only stub: one Auto Intro section covering the full duration.

    This is NOT a production-safe default. Downstream cue generation, validation,
    and editing treat the section list as authoritative. A silently returned
    one-section fake plan masks wiring bugs. Only callers that explicitly opt in
    via `allow_minimal_fallback=True` on `resolve_show_sections` should see this
    shape — tests and local demo only.
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
    allow_minimal_fallback: bool = False,
    laser_program_version: int = _LASER_PROGRAM_VERSION,
    show_section_generator_version: int = _SHOW_SECTION_GENERATOR_VERSION,
    cue_recipe_version: int = _CUE_RECIPE_VERSION,
) -> list[dict[str, Any]]:
    """Load persisted sections when sane, otherwise rebuild a dynamic default plan.

    Raises:
        ShowplanError: when ``default_show_sections_fn`` is not provided and
            ``allow_minimal_fallback`` is False. This is the production-safe
            default — a missing builder is a wiring bug, not a degradation path.
    """
    _normalize_selection_mode = normalize_selection_mode or _identity_selection_mode
    _normalize_selection_variance = normalize_selection_variance or _identity_selection_variance
    _normalize_venue_mode = normalize_venue_mode or _identity_venue_mode
    if default_show_sections_fn is not None:
        _default_show_sections = default_show_sections_fn
    elif allow_minimal_fallback:
        _default_show_sections = _single_auto_intro_fallback
    else:
        raise ShowplanError(
            "resolve_show_sections requires default_show_sections_fn "
            "(or allow_minimal_fallback=True for test/demo callers). "
            "Returning a one-section fallback in production would mask wiring bugs."
        )

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


def fixture_capability_graph(venue_mode: str) -> dict[str, dict[str, Any]]:
    venue = _normalize_venue_mode_fn(venue_mode)
    if venue == "medium_room_150_400":
        laser_geometries = {
            "intro": ["fan", "scan", "sky", "cone", "trace", "helix", "sheet"],
            "build": ["fan", "scan", "cone", "rake", "helix", "trace", "sheet", "tunnel", "grouped"],
            "drop": ["fan", "scan", "sheet", "tunnel", "helix", "trace", "cone", "grouped", "lattice", "burst", "array"],
            "outro": ["fan", "scan", "sky", "cone", "trace", "helix", "sheet"],
        }
        return {
            "laser": {
                "supports_hero": True,
                "allowed_geometries": laser_geometries,
                "max_density_cap": 0.86,
                "max_motion_scale": 1.05,
            },
            "mover": {"supports_hero": True, "max_motion_scale": 1.0},
            "wash": {"supports_hero": True, "max_motion_scale": 0.8},
            "led": {"supports_hero": True, "max_motion_scale": 0.9},
        }
    laser_geometries = {
        "intro": ["fan", "scan", "sky", "cone", "trace", "helix"],
        "build": ["fan", "scan", "cone", "rake", "helix", "trace"],
        "drop": ["fan", "scan", "sheet", "tunnel", "helix", "trace", "cone"],
        "outro": ["fan", "scan", "sky", "cone", "trace", "helix"],
    }
    return {
        "laser": {
            "supports_hero": False,
            "allowed_geometries": laser_geometries,
            "max_density_cap": 0.72,
            "max_motion_scale": 0.85,
        },
        "mover": {"supports_hero": True, "max_motion_scale": 0.9},
        "wash": {"supports_hero": True, "max_motion_scale": 0.7},
        "led": {"supports_hero": True, "max_motion_scale": 0.8},
    }


def _capability_stage_for_role(section_role: str) -> str:
    if section_role in {"build_1", "build_2"}:
        return "build"
    if section_role in {"drop_1", "drop_variation"}:
        return "drop"
    if section_role == "outro":
        return "outro"
    return "intro"


def compatible_laser_pattern(
    *,
    base_pattern: str,
    kind: str,
    context: str,
    profile: dict[str, Any],
    section_role: str,
    venue_mode: str,
) -> tuple[str, list[str]]:
    capability_graph = fixture_capability_graph(venue_mode)
    allowed_geometries = set(
        capability_graph["laser"]["allowed_geometries"].get(
            _capability_stage_for_role(section_role),
            capability_graph["laser"]["allowed_geometries"]["intro"],
        )
    )
    geometry = _LASER_PATTERN_GEOMETRY.get(base_pattern, "fan")
    if geometry in allowed_geometries:
        return base_pattern, []

    candidates = _pattern_candidates(
        family="laser",
        kind=kind,
        context=context,
        profile=profile,
    )
    for candidate in candidates:
        candidate_geometry = _LASER_PATTERN_GEOMETRY.get(candidate, "fan")
        if candidate_geometry in allowed_geometries:
            return candidate, [
                f"laser_pattern_degraded:{base_pattern}->{candidate}",
                f"unsupported_geometry:{geometry}",
            ]
    return base_pattern, [f"laser_pattern_unverified:{base_pattern}"]


def _sync_section_role_state(
    *,
    section: dict[str, Any],
    lead_family: str,
    fixture_role_map_value: dict[str, dict[str, Any]],
) -> None:
    section["lead_family"] = lead_family
    section["fixture_role_map"] = copy.deepcopy(fixture_role_map_value)
    cue_recipe = section.get("cue_recipe")
    if isinstance(cue_recipe, dict):
        cue_recipe["lead_family"] = lead_family
        cue_recipe["fixture_role_map"] = copy.deepcopy(fixture_role_map_value)
        families = cue_recipe.get("families")
        if isinstance(families, dict):
            for family, role_meta in fixture_role_map_value.items():
                family_payload = families.get(family)
                if not isinstance(family_payload, dict):
                    continue
                family_payload["role"] = str(role_meta.get("role") or "off")
                family_payload["coupling_mode"] = str(role_meta.get("coupling_mode") or "independent")
                family_payload["intensity_ceiling"] = float(role_meta.get("intensity_ceiling") or 0.0)
                enabled_key = {
                    "laser": "laser_enabled",
                    "mover": "movers_enabled",
                    "wash": "washes_enabled",
                    "led": "leds_enabled",
                }[family]
                family_payload["enabled"] = bool(section.get(enabled_key, family_payload.get("enabled")))


def _strobe_level_cap(*, section_role: str, venue_mode: str) -> float:
    venue = _normalize_venue_mode_fn(venue_mode)
    if section_role in {"intro", "vocal", "breakdown", "outro"}:
        return 0.0
    if section_role == "bridge":
        return 0.08
    if venue == "small_room_50_100":
        if section_role == "drop_variation":
            return 0.28
        if section_role == "drop_1":
            return 0.32
        if section_role in {"build_1", "build_2"}:
            return 0.18
        return 0.14
    if section_role == "drop_variation":
        return 0.42
    if section_role == "drop_1":
        return 0.46
    if section_role in {"build_1", "build_2"}:
        return 0.24
    return 0.16


def _apply_strobe_policy(section: dict[str, Any], venue_mode: str) -> None:
    section_role = str(section.get("section_role") or "")
    cap = _strobe_level_cap(section_role=section_role, venue_mode=venue_mode)
    current_level = float(section.get("strobe_level") or 0.0)
    level = round(_clamp(min(current_level, cap), 0.0, 1.0), 3)
    section["strobe_level"] = level
    profile = section.get("strobe_profile")
    if isinstance(profile, dict):
        profile["floor"] = round(min(float(profile.get("floor") or 0.0), level), 3)
        profile["ceiling"] = round(min(float(profile.get("ceiling") or 0.0), level), 3)
        if level <= 0:
            profile["mode"] = "restraint"
            profile["label"] = "restrained accents"


def _apply_laser_policy(section: dict[str, Any], venue_mode: str) -> None:
    section_role = str(section.get("section_role") or "")
    allowed = bool(section.get("laser_enabled", False))
    if section_role in {"vocal", "breakdown"}:
        allowed = False
    section["laser_enabled"] = allowed
    cue_recipe = section.get("cue_recipe")
    zone_policy = _apply_venue_laser_zone_policy(
        venue_mode,
        str(section.get("laser_program", {}).get("zone_policy") or _laser_zone_policy(str(section.get("kind") or ""), str(cue_recipe.get("intent") if isinstance(cue_recipe, dict) else ""))),
    )
    laser_program = section.get("laser_program")
    if isinstance(laser_program, dict):
        laser_program["zone_policy"] = zone_policy
    if isinstance(cue_recipe, dict):
        families = cue_recipe.get("families")
        if isinstance(families, dict) and isinstance(families.get("laser"), dict):
            families["laser"]["enabled"] = allowed
            families["laser"]["zone_policy"] = zone_policy


def _drop_variation_lead_family(section: dict[str, Any], previous_drop: dict[str, Any], venue_mode: str) -> str:
    current = str(section.get("lead_family") or "")
    previous = str(previous_drop.get("lead_family") or "")
    if current != previous and current:
        return current
    enabled = {
        "laser": bool(section.get("laser_enabled")),
        "mover": bool(section.get("movers_enabled")),
        "wash": bool(section.get("washes_enabled")),
        "led": bool(section.get("leds_enabled")),
    }
    venue = _normalize_venue_mode_fn(venue_mode)
    preference = ["led", "mover", "wash", "laser"] if venue == "small_room_50_100" else ["laser", "led", "mover", "wash"]
    for family in preference:
        if enabled[family] and family != previous:
            return family
    return current or previous or "wash"


def apply_show_section_validators(
    sections: list[dict[str, Any]],
    *,
    venue_mode: str,
) -> list[dict[str, Any]]:
    validated = [copy.deepcopy(section) for section in sections]
    previous_drop: dict[str, Any] | None = None
    for section in validated:
        section_role = str(section.get("section_role") or "")
        current_lead = str(section.get("lead_family") or "")
        if section_role == "drop_variation" and previous_drop is not None:
            current_lead = _drop_variation_lead_family(section, previous_drop, venue_mode)
        lead_family, fixture_role_map_value = fixture_role_map(
            section_role=section_role,
            venue_mode=venue_mode,
            laser_enabled=bool(section.get("laser_enabled")),
            movers_enabled=bool(section.get("movers_enabled")),
            washes_enabled=bool(section.get("washes_enabled")),
            leds_enabled=bool(section.get("leds_enabled")),
            preferred_lead_family=current_lead,
        )
        _sync_section_role_state(section=section, lead_family=lead_family, fixture_role_map_value=fixture_role_map_value)
        _apply_strobe_policy(section, venue_mode)
        _apply_laser_policy(section, venue_mode)
        if section_role in {"drop_1", "drop_variation"}:
            previous_drop = section
    return validated


def scene_for_marker_kind(kind: str) -> str:
    if kind == "drop":
        return "drop_intense"
    if kind == "build":
        return "break_sweep"
    if kind in {"breakdown", "bridge", "verse", "vocal"}:
        return "intro_ambient"
    if kind == "outro":
        return "intro_ambient"
    return "intro_ambient"


def fixture_mode_for_marker_kind(kind: str) -> str:
    if kind == "drop":
        return "peak_return"
    if kind == "build":
        return "rebuild"
    if kind in {"breakdown", "bridge", "verse", "vocal"}:
        return "breakdown"
    if kind == "outro":
        return "outro"
    return "intro"


def venue_profile(venue_mode: str | None) -> dict[str, Any]:
    normalized = _normalize_venue_mode_fn(venue_mode)
    if normalized == "medium_room_150_400":
        return {
            "mode": normalized,
            "indoor": True,
            "capacity_range": [150, 400],
            "ceiling_height_class": "medium",
            "throw_distance_class": "medium",
            "audience_depth_class": "medium",
            "laser_policy": "overhead_bias",
            "readability_bias": "balanced",
            "intensity_scale": 1.0,
            "motion_scale": 1.0,
            "strobe_scale": 0.82,
            "density_cap": 0.86,
            "whiteout_budget": 0.8,
            "max_dense_layers": 2,
        }
    return {
        "mode": "small_room_50_100",
        "indoor": True,
        "capacity_range": [50, 100],
        "ceiling_height_class": "low_medium",
        "throw_distance_class": "short",
        "audience_depth_class": "shallow",
        "laser_policy": "overhead_only",
        "readability_bias": "intimate",
        "intensity_scale": 0.93,
        "motion_scale": 0.9,
        "strobe_scale": 0.62,
        "density_cap": 0.72,
        "whiteout_budget": 0.66,
        "max_dense_layers": 2,
    }


def default_show_sections(
    markers: list[dict[str, Any]],
    duration_seconds: float,
    *,
    track_seed: str | None = None,
    semantic_profile: dict[str, Any] | None = None,
    selection_mode: str = "procedural",
    selection_variance: float = 0.0,
    venue_mode: str = "small_room_50_100",
    metadata_confidence: dict[str, Any] | None = None,
    normalize_selection_mode_fn: Callable[[str | None], str],
    normalize_selection_variance_fn: Callable[[Any | None], float],
    normalize_venue_mode_fn: Callable[[str | None], str],
    creative_profile_fn: Callable[[str | None, list[dict[str, Any]]], tuple[str, dict[str, Any]]],
    decorate_show_sections_with_motifs_fn: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
    select_section_patterns_fn: Callable[..., dict[str, str]],
    cue_recipe_fn: Callable[..., dict[str, Any]],
    laser_program_fn: Callable[..., dict[str, Any]],
    auto_markers_fn: Callable[[float], list[dict[str, Any]]],
    section_levels_fn: Callable[..., tuple[float, float, float]],
    strobe_profile_fn: Callable[..., dict[str, Any]],
    fixture_enablement_fn: Callable[..., tuple[bool, bool, bool, bool]],
    laser_variant_fn: Callable[..., dict[str, Any]],
    laser_expression_fn: Callable[..., dict[str, Any]],
    mover_variant_fn: Callable[..., dict[str, Any]],
    wash_variant_fn: Callable[..., dict[str, Any]],
    led_variant_fn: Callable[..., dict[str, Any]],
    cue_family_id_fn: Callable[[str, str, str], str],
    show_section_generator_version: int = _SHOW_SECTION_GENERATOR_VERSION,
) -> list[dict[str, Any]]:
    if not markers:
        markers = auto_markers_fn(duration_seconds)

    seed = track_seed or "unknown-track"
    selection_mode = normalize_selection_mode_fn(selection_mode)
    selection_variance = normalize_selection_variance_fn(selection_variance)
    venue_mode = normalize_venue_mode_fn(venue_mode)
    venue_profile_value = venue_profile(venue_mode)
    capability_graph = fixture_capability_graph(venue_mode)
    _, profile = creative_profile_fn(seed, markers)
    total_counts: dict[str, int] = {}
    for marker in markers:
        marker_kind = str(marker["kind"])
        total_counts[marker_kind] = total_counts.get(marker_kind, 0) + 1

    sections: list[dict[str, Any]] = []
    previous_patterns: dict[str, str | None] = {"laser": None, "mover": None, "wash": None, "led": None}
    pattern_history: dict[str, list[str]] = {"laser": [], "mover": [], "wash": [], "led": []}
    usage_count_by_family: dict[str, dict[str, int]] = {"laser": {}, "mover": {}, "wash": {}, "led": {}}
    kind_counts: dict[str, int] = {}
    previous_section_role: str | None = None
    ordered = sorted(markers, key=lambda item: float(item["start_seconds"]))
    for index, marker in enumerate(ordered):
        next_start = (
            float(ordered[index + 1]["start_seconds"])
            if index + 1 < len(ordered)
            else float(duration_seconds)
        )
        kind = str(marker["kind"])
        ordinal = kind_counts.get(kind, 0)
        kind_counts[kind] = ordinal + 1
        previous_kind = str(ordered[index - 1]["kind"]) if index > 0 else None
        next_kind = str(ordered[index + 1]["kind"]) if index + 1 < len(ordered) else None
        context = transition_context(
            previous_kind=previous_kind,
            kind=kind,
            next_kind=next_kind,
            ordinal=ordinal,
            total_of_kind=total_counts.get(kind, 1),
        )
        energy_hint = marker.get("energy_hint")
        energy_scale = max(0.25, min(1.0, float(energy_hint or 6) / 8.0))
        intensity_multiplier, motion_multiplier, strobe_level = section_levels_fn(
            kind=kind,
            context=context,
            energy_scale=energy_scale,
            profile=profile,
            ordinal=ordinal,
        )
        intensity_multiplier = round(
            _clamp(float(intensity_multiplier) * float(venue_profile_value["intensity_scale"]), 0.15, 1.35),
            3,
        )
        motion_multiplier = round(
            _clamp(float(motion_multiplier) * float(venue_profile_value["motion_scale"]), 0.2, 1.4),
            3,
        )
        strobe_level = round(
            _clamp(float(strobe_level) * float(venue_profile_value["strobe_scale"]), 0.0, 1.0),
            3,
        )
        strobe_profile_value = strobe_profile_fn(
            kind=kind,
            context=context,
            track_seed=seed,
            ordinal=ordinal,
            base_level=strobe_level,
        )
        section_role = normalize_section_role(
            kind=kind,
            marker_name=str(marker["name"]),
            context=context,
            ordinal=ordinal,
            total_of_kind=total_counts.get(kind, 1),
        )
        section_patterns = select_section_patterns_fn(
            kind=kind,
            context=context,
            profile=profile,
            track_seed=seed,
            marker_name=str(marker["name"]),
            ordinal=ordinal,
            previous_patterns=previous_patterns,
            pattern_history=pattern_history,
            usage_count_by_family=usage_count_by_family,
            semantic_profile=semantic_profile,
            selection_mode=selection_mode,
            energy_scale=energy_scale,
            selection_variance=selection_variance,
        )
        laser_pattern = section_patterns["laser"]
        mover_pattern = section_patterns["mover"]
        wash_pattern = section_patterns["wash"]
        led_pattern = section_patterns["led"]
        capability_notes: list[str] = []
        laser_pattern, laser_capability_notes = compatible_laser_pattern(
            base_pattern=laser_pattern,
            kind=kind,
            context=context,
            profile=profile,
            section_role=section_role,
            venue_mode=venue_mode,
        )
        capability_notes.extend(laser_capability_notes)
        previous_patterns.update({
            "laser": laser_pattern,
            "mover": mover_pattern,
            "wash": wash_pattern,
            "led": led_pattern,
        })
        for family, pattern in section_patterns.items():
            pattern_history[family].append(pattern)
            usage_count_by_family[family][pattern] = usage_count_by_family[family].get(pattern, 0) + 1
        laser_enabled, movers_enabled, washes_enabled, leds_enabled = fixture_enablement_fn(
            kind=kind,
            context=context,
            profile=profile,
            track_seed=seed,
            ordinal=ordinal,
        )
        lead_family, fixture_role_map_value = fixture_role_map(
            section_role=section_role,
            venue_mode=venue_mode,
            laser_enabled=laser_enabled,
            movers_enabled=movers_enabled,
            washes_enabled=washes_enabled,
            leds_enabled=leds_enabled,
        )
        next_section_role = None
        if index + 1 < len(ordered):
            next_marker = ordered[index + 1]
            next_kind_value = str(next_marker["kind"])
            next_total_of_kind = total_counts.get(next_kind_value, 1)
            next_ordinal = kind_counts.get(next_kind_value, 0)
            next_context = transition_context(
                previous_kind=kind,
                kind=next_kind_value,
                next_kind=str(ordered[index + 2]["kind"]) if index + 2 < len(ordered) else None,
                ordinal=next_ordinal,
                total_of_kind=next_total_of_kind,
            )
            next_section_role = normalize_section_role(
                kind=next_kind_value,
                marker_name=str(next_marker["name"]),
                context=next_context,
                ordinal=next_ordinal,
                total_of_kind=next_total_of_kind,
            )
        transition_intent_value = transition_intent(
            section_role=section_role,
            context=context,
            previous_role=previous_section_role,
            next_role=next_section_role,
        )
        cue_family_id_value = cue_family_id_fn(section_role, lead_family, venue_mode)
        laser_variant_value = laser_variant_fn(
            track_seed=seed,
            base_pattern=laser_pattern,
            kind=kind,
            context=context,
            ordinal=ordinal,
        )
        laser_expression_value = laser_expression_fn(
            track_seed=seed,
            base_pattern=laser_pattern,
            kind=kind,
            context=context,
            ordinal=ordinal,
        )
        mover_variant_value = mover_variant_fn(
            track_seed=seed,
            base_pattern=mover_pattern,
            kind=kind,
            context=context,
            ordinal=ordinal,
        )
        wash_variant_value = wash_variant_fn(
            track_seed=seed,
            base_pattern=wash_pattern,
            kind=kind,
            context=context,
            ordinal=ordinal,
        )
        led_variant_value = led_variant_fn(
            track_seed=seed,
            base_pattern=led_pattern,
            kind=kind,
            context=context,
            ordinal=ordinal,
        )
        cue_recipe_value = cue_recipe_fn(
            kind=kind,
            context=context,
            laser_pattern=laser_pattern,
            mover_pattern=mover_pattern,
            wash_pattern=wash_pattern,
            led_pattern=led_pattern,
            laser_enabled=laser_enabled,
            movers_enabled=movers_enabled,
            washes_enabled=washes_enabled,
            leds_enabled=leds_enabled,
            section_role=section_role,
            venue_mode=venue_mode,
            venue_profile=venue_profile_value,
            transition_intent=transition_intent_value,
            cue_family_id=cue_family_id_value,
            lead_family=lead_family,
            fixture_role_map=fixture_role_map_value,
            capability_graph=capability_graph,
            capability_notes=capability_notes,
            metadata_confidence=metadata_confidence,
        )
        sections.append(
            {
                "generator_version": show_section_generator_version,
                "id": f"section_{index:03d}",
                "label": str(marker["name"]),
                "kind": kind,
                "section_role": section_role,
                "venue_mode": venue_mode,
                "venue_profile": copy.deepcopy(venue_profile_value),
                "cue_family_id": cue_family_id_value,
                "lead_family": lead_family,
                "fixture_role_map": copy.deepcopy(fixture_role_map_value),
                "transition_intent": copy.deepcopy(transition_intent_value),
                "fixture_capability_graph": copy.deepcopy(capability_graph),
                "capability_notes": list(capability_notes),
                "start_seconds": round(float(marker["start_seconds"]), 3),
                "end_seconds": round(max(float(marker["start_seconds"]), next_start), 3),
                "scene_id": scene_for_marker_kind(kind),
                "fixture_mode": fixture_mode_for_marker_kind(kind),
                "intensity_multiplier": intensity_multiplier,
                "motion_multiplier": motion_multiplier,
                "strobe_level": strobe_level,
                "strobe_profile": strobe_profile_value,
                "laser_pattern": laser_pattern,
                "laser_variant": laser_variant_value,
                "laser_expression": laser_expression_value,
                "laser_program": laser_program_fn(
                    track_seed=seed,
                    base_pattern=laser_pattern,
                    kind=kind,
                    context=context,
                    ordinal=ordinal,
                    profile=profile,
                    venue_mode=venue_mode,
                ),
                "cue_recipe": cue_recipe_value,
                "mover_pattern": mover_pattern,
                "mover_variant": mover_variant_value,
                "wash_pattern": wash_pattern,
                "wash_variant": wash_variant_value,
                "led_pattern": led_pattern,
                "led_variant": led_variant_value,
                "laser_enabled": laser_enabled,
                "movers_enabled": movers_enabled,
                "washes_enabled": washes_enabled,
                "leds_enabled": leds_enabled,
            }
        )
        previous_section_role = section_role
    validated_sections = apply_show_section_validators(sections, venue_mode=venue_mode)
    return decorate_show_sections_with_motifs_fn(validated_sections)
