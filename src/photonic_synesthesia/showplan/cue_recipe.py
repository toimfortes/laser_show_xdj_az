"""Cue recipe builder for the showplan facade."""

from __future__ import annotations

import copy
from typing import Any

from photonic_synesthesia.showplan.types import (
    CUE_RECIPE_VERSION as _CUE_RECIPE_VERSION,
    VENUE_MODES as _VENUE_MODES,
    apply_venue_laser_zone_policy as _apply_venue_laser_zone_policy,
    clamp as _clamp,
    cue_family_id as _cue_family_id,
    laser_zone_policy as _laser_zone_policy,
    normalize_venue_mode as _normalize_venue_mode,
    pattern_stage as _pattern_stage,
    safe_confidence_value as _safe_confidence_value,
)


def _cue_recipe_group_name(*, family: str, stage: str) -> str:
    if family == "laser":
        return {
            "drop": "laser_all",
            "build": "laser_main",
            "breakdown": "laser_texture",
            "outro": "laser_texture",
        }.get(stage, "laser_main")
    if family == "mover":
        return {
            "drop": "movers_impact",
            "build": "movers_build",
            "breakdown": "movers_texture",
            "outro": "movers_texture",
        }.get(stage, "movers_main")
    if family == "wash":
        return {
            "drop": "washes_impact",
            "build": "washes_build",
            "breakdown": "washes_texture",
            "outro": "washes_texture",
        }.get(stage, "washes_main")
    return {
        "drop": "leds_impact",
        "build": "leds_build",
        "breakdown": "leds_texture",
        "outro": "leds_texture",
    }.get(stage, "leds_main")


def _cue_recipe_feature_group(family: str) -> str:
    return {
        "laser": "Beam",
        "mover": "Position",
        "wash": "Color",
        "led": "Pixel",
    }[family]


def _cue_recipe_timing_master(stage: str, context: str) -> str:
    if stage == "drop":
        return "tm_drop_groove" if context == "drop_variation" else "tm_drop_impact"
    if stage == "build":
        return "tm_build_cycle" if context == "build_cycle" else "tm_build_riser"
    if stage == "breakdown":
        return "tm_breakdown_release"
    if stage == "outro":
        return "tm_outro_release"
    return "tm_intro_glide"


def _cue_recipe_transition_strategy(stage: str, context: str) -> str:
    if stage == "drop":
        return "impact" if context == "drop_launch" else "sustain_release"
    if stage == "build":
        return "escalate" if context == "build_riser" else "develop"
    if stage == "breakdown":
        return "release"
    if stage == "outro":
        return "dissolve"
    return "set"


def _phaser_family_name(*, family: str, stage: str, context: str, pattern: str) -> str:
    if family == "laser":
        if stage == "drop":
            return "laser_drop_sweep" if context == "drop_launch" else "laser_afterglow_drift"
        if stage == "build":
            return "laser_riser_contract"
        if stage == "breakdown":
            return "laser_trace_follow"
        return "laser_breathe_8bar"
    if family == "mover":
        if stage == "drop":
            return "mover_drop_sweep"
        if stage == "build":
            return "mover_diagonal_push"
        if pattern in {"drift", "leaf", "hold"}:
            return "mover_afterglow_drift"
        return "mover_groove_call_response"
    if family == "wash":
        return "wash_breathe_8bar" if stage in {"intro", "breakdown", "outro"} else "wash_phrase_bloom"
    return "led_pixel_hook" if stage in {"build", "drop"} else "led_afterglow_drift"


def _phaser_family(
    *,
    family: str,
    stage: str,
    context: str,
    pattern: str,
    timing_master: str,
    role_meta: dict[str, Any],
) -> dict[str, Any]:
    sync_mode = "phrase_locked" if stage in {"intro", "breakdown", "outro"} else "beat"
    measure = 4 if stage in {"build", "drop"} else 8
    transition_profile = "smooth" if stage in {"intro", "breakdown", "outro"} else "punctuated"
    width_profile = "wide" if str(role_meta.get("role") or "") in {"hero", "support"} else "narrow"
    return {
        "family": _phaser_family_name(
            family=family,
            stage=stage,
            context=context,
            pattern=pattern,
        ),
        "target_family": family,
        "pattern": pattern,
        "measure": measure,
        "width_profile": width_profile,
        "transition_profile": transition_profile,
        "phase_distribution": "sym_wide" if str(role_meta.get("coupling_mode") or "") in {"mirror", "widen"} else "linear",
        "sync_mode": sync_mode,
        "timing_master": timing_master,
        "free_run": stage in {"intro", "breakdown", "outro"} and family in {"wash", "led"},
    }


def _recipe_line(
    *,
    family: str,
    pattern: str,
    stage: str,
    timing_master: str,
    role_meta: dict[str, Any],
    enabled: bool,
    zone_policy: str = "",
) -> dict[str, Any]:
    line = {
        "group_ref": _cue_recipe_group_name(family=family, stage=stage),
        "preset_ref": f"{family}/{stage}/{pattern}",
        "feature_group": _cue_recipe_feature_group(family),
        "matricks_ref": "sym_wide" if str(role_meta.get("coupling_mode") or "") in {"mirror", "widen"} else "linear",
        "speed_ref": timing_master,
        "phase_ref": "0..300" if str(role_meta.get("role") or "") == "hero" else "0..180",
        "merge_mode": "layered",
        "enabled": enabled,
    }
    if family == "laser":
        line["zone_policy"] = zone_policy
    return line


def _recipe_bundle(
    *,
    section_role: str,
    venue_mode: str,
    timing_master: str,
    lead_family: str,
    transition_intent: dict[str, Any],
    recipe_lines: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "cue_family_id": _cue_family_id(
            section_role,
            lead_family,
            venue_mode,
        ),
        "lead_family": lead_family,
        "timing_master": timing_master,
        "transition_intent": copy.deepcopy(transition_intent),
        "recipe_lines": copy.deepcopy(recipe_lines),
    }


def _trigger_policy(
    *,
    section_role: str,
    metadata_confidence: dict[str, Any] | None,
) -> dict[str, Any]:
    confidence = metadata_confidence if isinstance(metadata_confidence, dict) else {}
    transport_confidence = _safe_confidence_value(confidence.get("transport_confidence"), default=0.2)
    phrase_confidence = _safe_confidence_value(confidence.get("phrase_confidence"), default=0.2)
    beatgrid_confidence = _safe_confidence_value(confidence.get("beatgrid_confidence"), default=0.2)

    if transport_confidence >= 0.9 and phrase_confidence >= 0.85:
        primary = "phrase_head"
        fallback = "next_downbeat"
        tier = "strict"
    elif beatgrid_confidence >= 0.72:
        primary = "next_downbeat"
        fallback = "bar_head"
        tier = "beat_safe"
    else:
        primary = "section_estimate"
        fallback = "free_run"
        tier = "degraded"

    if section_role in {"intro", "outro", "breakdown", "vocal"} and primary == "phrase_head":
        fallback = "bar_head"
    if section_role in {"drop_1", "drop_variation"} and tier == "degraded":
        fallback = "bar_head"

    return {
        "primary": primary,
        "fallback": fallback,
        "confidence_tier": tier,
        "phrase_confidence": phrase_confidence,
        "transport_confidence": transport_confidence,
        "beatgrid_confidence": beatgrid_confidence,
    }


def _cue_recipe_family(
    *,
    family: str,
    pattern: str,
    stage: str,
    timing_master: str,
    enabled: bool,
    role_meta: dict[str, Any],
    phaser_family: dict[str, Any],
    recipe_line: dict[str, Any],
    zone_policy: str = "",
) -> dict[str, Any]:
    payload = {
        "enabled": enabled,
        "group": _cue_recipe_group_name(family=family, stage=stage),
        "feature_group": _cue_recipe_feature_group(family),
        "preset": f"{family}/{stage}/{pattern}",
        "effect": f"phaser/{family}/{pattern}",
        "timing_master": timing_master,
        "pattern": pattern,
        "role": str(role_meta.get("role") or "off"),
        "coupling_mode": str(role_meta.get("coupling_mode") or "independent"),
        "intensity_ceiling": float(role_meta.get("intensity_ceiling") or 0.0),
        "phaser_family": copy.deepcopy(phaser_family),
        "recipe_line": copy.deepcopy(recipe_line),
    }
    if family == "laser":
        payload["zone_policy"] = zone_policy
    return payload


def build_cue_recipe(
    *,
    kind: str,
    context: str,
    laser_pattern: str,
    mover_pattern: str,
    wash_pattern: str,
    led_pattern: str,
    laser_enabled: bool,
    movers_enabled: bool,
    washes_enabled: bool,
    leds_enabled: bool,
    section_role: str,
    venue_mode: str,
    venue_profile: dict[str, Any],
    transition_intent: dict[str, Any],
    cue_family_id: str,
    lead_family: str,
    fixture_role_map: dict[str, dict[str, Any]],
    capability_graph: dict[str, dict[str, Any]],
    capability_notes: list[str],
    metadata_confidence: dict[str, Any] | None,
    cue_recipe_version: int = _CUE_RECIPE_VERSION,
) -> dict[str, Any]:
    stage = _pattern_stage(kind)
    timing_master = _cue_recipe_timing_master(stage, context)
    zone_policy = _apply_venue_laser_zone_policy(venue_mode, _laser_zone_policy(kind, context))
    family_configs = {
        "laser": {
            "pattern": laser_pattern,
            "enabled": laser_enabled,
            "zone_policy": zone_policy,
        },
        "mover": {
            "pattern": mover_pattern,
            "enabled": movers_enabled,
            "zone_policy": "",
        },
        "wash": {
            "pattern": wash_pattern,
            "enabled": washes_enabled,
            "zone_policy": "",
        },
        "led": {
            "pattern": led_pattern,
            "enabled": leds_enabled,
            "zone_policy": "",
        },
    }
    compiled_families: dict[str, dict[str, Any]] = {}
    phaser_bundle: list[dict[str, Any]] = []
    recipe_lines: list[dict[str, Any]] = []
    for family in ("laser", "mover", "wash", "led"):
        family_config = family_configs[family]
        role_meta = fixture_role_map.get(family, {})
        phaser_family = _phaser_family(
            family=family,
            stage=stage,
            context=context,
            pattern=str(family_config["pattern"]),
            timing_master=timing_master,
            role_meta=role_meta,
        )
        recipe_line = _recipe_line(
            family=family,
            pattern=str(family_config["pattern"]),
            stage=stage,
            timing_master=timing_master,
            role_meta=role_meta,
            enabled=bool(family_config["enabled"]),
            zone_policy=str(family_config["zone_policy"]),
        )
        compiled_family = _cue_recipe_family(
            family=family,
            pattern=str(family_config["pattern"]),
            stage=stage,
            timing_master=timing_master,
            enabled=bool(family_config["enabled"]),
            role_meta=role_meta,
            phaser_family=phaser_family,
            recipe_line=recipe_line,
            zone_policy=str(family_config["zone_policy"]),
        )
        compiled_families[family] = compiled_family
        phaser_bundle.append(copy.deepcopy(phaser_family))
        if compiled_family["enabled"]:
            recipe_lines.append(copy.deepcopy(recipe_line))
    recipe_bundle = _recipe_bundle(
        section_role=section_role,
        venue_mode=venue_mode,
        timing_master=timing_master,
        lead_family=lead_family,
        transition_intent=transition_intent,
        recipe_lines=recipe_lines,
    )
    trigger_policy = _trigger_policy(
        section_role=section_role,
        metadata_confidence=metadata_confidence,
    )
    return {
        "version": cue_recipe_version,
        "intent": context,
        "stage": stage,
        "section_role": section_role,
        "venue_mode": _normalize_venue_mode(venue_mode),
        "venue_profile": copy.deepcopy(venue_profile),
        "cue_family_id": cue_family_id,
        "lead_family": lead_family,
        "transition_strategy": _cue_recipe_transition_strategy(stage, context),
        "transition_intent": copy.deepcopy(transition_intent),
        "timing_master": timing_master,
        "trigger_policy": trigger_policy,
        "fixture_role_map": copy.deepcopy(fixture_role_map),
        "fixture_capability_graph": copy.deepcopy(capability_graph),
        "capability_notes": list(capability_notes),
        "recipe_lines": copy.deepcopy(recipe_lines),
        "phaser_bundle": copy.deepcopy(phaser_bundle),
        "recipe_bundle": recipe_bundle,
        "families": compiled_families,
    }
