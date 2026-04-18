"""Operator-intent helpers for runtime playback context."""

from __future__ import annotations

import copy
from typing import Any

from photonic_synesthesia.platform.runtime_context_normalization import clamp
from photonic_synesthesia.platform.runtime_context_section_mutations import (
    promote_family_to_hero,
    set_family_intensity,
    update_operator_override,
)


def intent_expired(
    intent_payload: dict[str, Any],
    show_sections: list[dict[str, Any]],
    playhead_seconds: float,
    duration_seconds: float,
) -> bool:
    expires_at = str(intent_payload.get("expires_at") or "").strip().lower().replace("-", "_")
    if not expires_at:
        return False
    if expires_at == "end_of_track":
        return playhead_seconds >= max(0.0, duration_seconds)
    if expires_at == "next_phrase":
        target_ids = set(str(item) for item in list(intent_payload.get("target_ids") or []))
        if not target_ids:
            return False
        for section in show_sections:
            if str(section.get("id") or "") in target_ids:
                return playhead_seconds >= float(section.get("end_seconds") or 0.0)
        return False
    if expires_at == "next_drop":
        applied_playhead = float(intent_payload.get("applied_playhead_seconds") or 0.0)
        for section in show_sections:
            if str(section.get("section_role") or "").startswith("drop") and float(section.get("start_seconds") or 0.0) > applied_playhead:
                return playhead_seconds >= float(section.get("start_seconds") or 0.0)
        return False
    if expires_at.startswith("at:"):
        try:
            threshold = float(expires_at.split(":", 1)[1])
        except (TypeError, ValueError):
            return False
        return playhead_seconds >= threshold
    return False


def apply_operator_intent_to_section(
    section: dict[str, Any],
    *,
    intent: str,
    target: str,
    amount: float,
    duration_seconds: float,
) -> dict[str, Any]:
    updated = copy.deepcopy(section)
    cue_recipe = updated.get("cue_recipe")
    family_target = {
        "lasers": "laser",
        "movers": "mover",
        "washes": "wash",
        "leds": "led",
    }.get(target, "")

    if intent in {"darken", "brighten"} and target in {"all", "lasers", "movers", "washes", "leds"}:
        scale = 1.0 - amount if intent == "darken" else 1.0 + amount
        if target == "all":
            updated["intensity_multiplier"] = round(
                clamp(float(updated.get("intensity_multiplier") or 0.0) * scale, 0.1, 1.5),
                3,
            )
        elif family_target:
            set_family_intensity(updated, family_target, scale)
        update_operator_override(updated, "intensity_bias", intent)

    if intent == "less_strobe" and target in {"all", "strobes"}:
        updated["strobe_level"] = round(
            clamp(float(updated.get("strobe_level") or 0.0) * (1.0 - amount), 0.0, 1.0),
            3,
        )
        strobe_profile = updated.get("strobe_profile")
        if isinstance(strobe_profile, dict):
            for field_name in ("ceiling", "floor"):
                if field_name in strobe_profile:
                    strobe_profile[field_name] = round(
                        clamp(float(strobe_profile.get(field_name) or 0.0) * (1.0 - amount), 0.0, 1.0),
                        3,
                    )
        update_operator_override(updated, "strobe_bias", "reduced")

    if intent == "reduce_laser_density" and target in {"all", "lasers"}:
        laser_expression = updated.get("laser_expression")
        if isinstance(laser_expression, dict) and "sweep_density" in laser_expression:
            laser_expression["sweep_density"] = round(
                clamp(float(laser_expression.get("sweep_density") or 0.0) * (1.0 - amount), 0.0, 2.0),
                3,
            )
        laser_program = updated.get("laser_program")
        if isinstance(laser_program, dict):
            for key in ("launch", "release"):
                payload = laser_program.get(key)
                if isinstance(payload, dict) and "density" in payload:
                    payload["density"] = round(
                        clamp(float(payload.get("density") or 0.0) * (1.0 - amount), 0.0, 2.0),
                        3,
                    )
            for key in ("sustain", "fills"):
                looks = laser_program.get(key)
                if isinstance(looks, list):
                    for look in looks:
                        if isinstance(look, dict) and "density" in look:
                            look["density"] = round(
                                clamp(float(look.get("density") or 0.0) * (1.0 - amount), 0.0, 2.0),
                                3,
                            )
        update_operator_override(updated, "laser_density", "reduced")

    if intent == "favor_overhead" and target in {"all", "lasers"}:
        laser_program = updated.get("laser_program")
        if isinstance(laser_program, dict):
            laser_program["zone_policy"] = "overhead_only"
        if isinstance(cue_recipe, dict):
            families = cue_recipe.get("families")
            if isinstance(families, dict) and isinstance(families.get("laser"), dict):
                families["laser"]["zone_policy"] = "overhead_only"
                recipe_line = families["laser"].get("recipe_line")
                if isinstance(recipe_line, dict):
                    recipe_line["zone_policy"] = "overhead_only"
        update_operator_override(updated, "target_mode", "overhead")

    if intent == "freeze_hero_family":
        update_operator_override(updated, "hero_family_locked", str(updated.get("lead_family") or ""))

    if intent == "hold_current_palette":
        update_operator_override(updated, "palette_hold", True)

    if intent == "delay_peak":
        section_role = str(updated.get("section_role") or "")
        start_fraction = float(updated.get("start_seconds") or 0.0) / max(duration_seconds, 0.001)
        if section_role in {"build_2", "drop_1", "drop_variation"} and start_fraction < 0.7:
            updated["intensity_multiplier"] = round(
                clamp(float(updated.get("intensity_multiplier") or 0.0) * (1.0 - amount * 0.5), 0.1, 1.5),
                3,
            )
            updated["strobe_level"] = round(
                clamp(float(updated.get("strobe_level") or 0.0) * (1.0 - amount), 0.0, 1.0),
                3,
            )
            update_operator_override(updated, "peak_delay", True)

    if intent == "promote_washes" and target in {"all", "washes"} and bool(updated.get("washes_enabled")):
        promote_family_to_hero(updated, "wash")
        update_operator_override(updated, "wash_promoted", True)

    if family_target and isinstance(cue_recipe, dict):
        cue_recipe.setdefault("operator_targets", {})
        if isinstance(cue_recipe["operator_targets"], dict):
            cue_recipe["operator_targets"][intent] = family_target

    return updated
