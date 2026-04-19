"""Scorer bundle for showplan catalog entries.

Derives a small scalar rubric from the section list, anti-template
validation, and venue mode. The aggregate score + warnings gate
auto-accept in the catalog writer.

Previously lived in ``ui/cli.py`` and was injected via
``scorer_bundle_fn``; moved here so showplan calls directly.
"""

from __future__ import annotations

from typing import Any

from photonic_synesthesia.showplan.types import clamp as _clamp


def scorer_bundle(
    *,
    show_sections: list[dict[str, Any]],
    semantic_profile: dict[str, Any] | None,
    anti_template_validation: dict[str, Any],
    venue_mode: str,
) -> dict[str, Any]:
    structural_score = 1.0 if all(
        section.get("section_role") and section.get("cue_recipe") and section.get("transition_intent")
        for section in show_sections
    ) else 0.45
    hero_lock_ok = all(
        len([
            family
            for family, payload in dict(section.get("fixture_role_map") or {}).items()
            if str(payload.get("role") or "") == "hero"
        ]) == 1
        for section in show_sections
    )
    fixture_hierarchy = 1.0 if hero_lock_ok else 0.5
    intensity_values = [float(section.get("intensity_multiplier") or 0.0) for section in show_sections]
    motion_values = [float(section.get("motion_multiplier") or 0.0) for section in show_sections]
    strobe_values = [float(section.get("strobe_level") or 0.0) for section in show_sections]
    visual_contrast = round(
        _clamp(
            (max(intensity_values, default=0.0) - min(intensity_values, default=0.0)) * 0.45
            + (max(motion_values, default=0.0) - min(motion_values, default=0.0)) * 0.35
            + (max(strobe_values, default=0.0) - min(strobe_values, default=0.0)) * 0.2,
            0.0,
            1.0,
        ),
        3,
    )
    genre_hints = [str(item).lower() for item in list((semantic_profile or {}).get("genre_hints") or [])]
    strobe_total = sum(strobe_values)
    genre_fit = 0.92
    if any("afro" in hint for hint in genre_hints) and strobe_total > 0.7:
        genre_fit = 0.62
    elif any("progressive" in hint or "melodic" in hint for hint in genre_hints) and strobe_total > 1.0:
        genre_fit = 0.74
    repetition_control = round(1.0 - float(anti_template_validation.get("mean_similarity") or 0.0), 3)
    climax_quality = 0.78
    drop_sections = [
        section for section in show_sections if str(section.get("section_role") or "").startswith("drop")
    ]
    if drop_sections:
        final_drop = drop_sections[-1]
        end_seconds = max(float(section.get("end_seconds") or 0.0) for section in show_sections) or 1.0
        if float(final_drop.get("start_seconds") or 0.0) / end_seconds >= 0.55:
            climax_quality = 0.92
    emotional_coherence = round(
        _clamp(
            0.58
            + (0.12 if genre_hints else 0.0)
            + (0.1 if venue_mode == "small_room_50_100" else 0.14)
            + (
                0.08
                if any(
                    str(section.get("transition_intent", {}).get("type") or "") == "suckout"
                    for section in show_sections
                )
                else 0.0
            ),
            0.0,
            1.0,
        ),
        3,
    )
    laser_mover_coordination = round(
        _clamp(
            sum(
                1.0
                for section in show_sections
                if not section.get("laser_enabled")
                or not section.get("movers_enabled")
                or str(section.get("lead_family") or "") != "laser"
                or str(section.get("cue_recipe", {}).get("families", {}).get("mover", {}).get("role") or "") != "hero"
            )
            / max(1, len(show_sections)),
            0.0,
            1.0,
        ),
        3,
    )
    scores = {
        "structural_correctness": round(structural_score, 3),
        "fixture_hierarchy": round(fixture_hierarchy, 3),
        "visual_contrast": visual_contrast,
        "emotional_coherence": emotional_coherence,
        "laser_mover_coordination": laser_mover_coordination,
        "genre_fit": round(genre_fit, 3),
        "repetition_control": repetition_control,
        "climax_quality": round(climax_quality, 3),
    }
    aggregate = round(
        scores["structural_correctness"] * 0.16
        + scores["fixture_hierarchy"] * 0.14
        + scores["visual_contrast"] * 0.13
        + scores["emotional_coherence"] * 0.13
        + scores["laser_mover_coordination"] * 0.12
        + scores["genre_fit"] * 0.1
        + scores["repetition_control"] * 0.12
        + scores["climax_quality"] * 0.1,
        3,
    )
    warnings: list[str] = []
    if anti_template_validation.get("status") == "fail":
        warnings.append("cross_track_similarity")
    if scores["fixture_hierarchy"] < 0.8:
        warnings.append("hero_lock")
    if scores["genre_fit"] < 0.75:
        warnings.append("genre_fit")
    if scores["climax_quality"] < 0.8:
        warnings.append("climax_curve")
    return {
        "version": 1,
        "scores": scores,
        "aggregate": aggregate,
        "warnings": warnings,
        "auto_accept": aggregate >= 0.82 and not warnings,
    }
