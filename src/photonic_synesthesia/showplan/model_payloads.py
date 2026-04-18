"""Catalog model payload builder for the showplan facade.

Assembles the per-section model payload that downstream consumers (recent
catalog, audit tooling) use to review selection decisions. Constants and
helpers here are duplicated from the CLI's pattern tables so this module
stays free of `photonic_synesthesia.ui.*` and `platform.runtime_context*`
imports. If these drift from the CLI's copies, tests will catch it.
"""

from __future__ import annotations

import copy
from typing import Any

from photonic_synesthesia.showplan._patterns import (
    _dedupe,
    _stable_digest,
    pattern_candidates,
    pattern_stage,
)
from photonic_synesthesia.showplan.types import (
    VENUE_MODES as _VENUE_MODES,
    clamp as _clamp,
    normalize_venue_mode as _normalize_venue_mode,
)

_OLLAMA_CPU_MAX_CANDIDATES = 6

_CREATIVE_PROFILES: dict[str, dict[str, Any]] = {
    "festival_peak": {
        "strobe_bias": 0.22,
        "motion_bias": 0.18,
        "intensity_bias": 0.08,
        "allow_intro_lasers": False,
        "allow_breakdown_lasers": False,
        "allow_intro_leds": True,
        "patterns": {
            "laser": {
                "build": ["vertical_rake", "horizontal_rake", "rotor", "cone", "scan_slice", "spiral_tunnel"],
                "drop": ["shutter_hits", "burst_fan", "starburst", "alternating_beam_groups", "split_zone_beams", "target_rotate_chase", "sheet", "mixed_beam_fx"],
            },
            "mover": {
                "build": ["rise", "mirror_fan", "figure_eight", "circle"],
                "drop": ["snap_hits", "cross_sweep", "ping_pong_tilt", "square", "diamond"],
            },
            "wash": {
                "drop": ["white_peak", "drop_slam", "downbeat_hit", "punch"],
            },
            "led": {
                "drop": ["chase", "fizzle", "audio_spectrum", "rotating_line", "snake"],
            },
        },
    },
    "euphoric_arc": {
        "strobe_bias": 0.08,
        "motion_bias": 0.12,
        "intensity_bias": 0.04,
        "allow_intro_lasers": True,
        "allow_breakdown_lasers": True,
        "allow_intro_leds": False,
        "patterns": {
            "laser": {
                "intro": ["fan", "beam_fan_narrow", "liquid_sky", "wave", "circle_trace"],
                "build": ["cone", "wave", "vertical_rake", "rotor", "loop_trace", "spiral_tunnel"],
                "drop": ["burst_fan", "tunnel", "starburst", "crisscross", "beam_fan_wide", "point_array"],
                "breakdown": ["liquid_sky", "thin_scan", "fan", "spirograph", "circle_trace"],
            },
            "mover": {
                "build": ["mirror_fan", "figure_eight", "rise", "circle"],
                "drop": ["cross_sweep", "diamond", "square", "snap_hits"],
            },
            "wash": {
                "intro": ["ambient", "breath", "center_out"],
                "build": ["bloom", "build_ramp", "outside_in"],
                "drop": ["white_peak", "punch", "drop_slam"],
                "breakdown": ["breakdown_glow", "fade", "ambient"],
            },
            "led": {
                "build": ["vertical_build", "ramp", "snake"],
                "drop": ["audio_spectrum", "rotating_line", "chase"],
            },
        },
    },
    "percussive_driver": {
        "strobe_bias": 0.18,
        "motion_bias": 0.1,
        "intensity_bias": 0.06,
        "allow_intro_lasers": False,
        "allow_breakdown_lasers": False,
        "allow_intro_leds": True,
        "patterns": {
            "laser": {
                "build": ["vertical_rake", "horizontal_rake", "cone", "scan_slice", "target_step_chase"],
                "drop": ["shutter_hits", "alternating_beam_groups", "burst_fan", "starburst", "split_zone_beams", "target_rotate_chase", "beam_sequence_counterclockwise"],
            },
            "mover": {
                "drop": ["snap_hits", "cross_sweep", "ping_pong_tilt", "line_bounce"],
            },
            "wash": {
                "drop": ["downbeat_hit", "drop_slam", "punch", "white_peak"],
            },
            "led": {
                "build": ["vertical_offset", "vertical_build", "ramp"],
                "drop": ["chase", "fizzle", "snake", "audio_spectrum"],
            },
        },
    },
    "hypnotic_motorik": {
        "strobe_bias": -0.04,
        "motion_bias": 0.14,
        "intensity_bias": -0.02,
        "allow_intro_lasers": True,
        "allow_breakdown_lasers": True,
        "allow_intro_leds": False,
        "patterns": {
            "laser": {
                "intro": ["wave", "liquid_sky", "fan", "wave_trace", "circle_trace"],
                "build": ["rotor", "cone", "wave", "vertical_rake", "loop_trace", "target_bounce_chase"],
                "drop": ["tunnel", "crisscross", "rotor", "burst_fan", "spiral_tunnel", "sheet"],
                "breakdown": ["liquid_sky", "wave", "thin_scan", "helix", "spirograph"],
            },
            "mover": {
                "intro": ["drift", "circle", "leaf"],
                "build": ["figure_eight", "circle", "mirror_fan"],
                "drop": ["cross_sweep", "square", "diamond", "ping_pong_tilt"],
                "breakdown": ["hold", "leaf", "drift"],
            },
            "wash": {
                "intro": ["ambient", "gradient_roll", "breath"],
                "build": ["gradient_roll", "bloom", "center_out"],
                "drop": ["punch", "white_peak", "downbeat_hit"],
            },
            "led": {
                "intro": ["pulse", "horizontal_lines", "fade"],
                "build": ["rotating_line", "ramp", "vertical_offset"],
                "drop": ["rotating_line", "audio_spectrum", "snake", "chase"],
            },
        },
    },
}




def _venue_profile(venue_mode: str | None) -> dict[str, Any]:
    normalized = _normalize_venue_mode(venue_mode)
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


def _auto_markers_for_duration(duration_seconds: float) -> list[dict[str, Any]]:
    """Generate phrase markers when no Rekordbox structure is available."""
    duration = max(1.0, float(duration_seconds))
    if duration <= 75:
        target_count = 4
    else:
        target_count = int(_clamp(round(duration / 28.0), 5, 10))

    template_kinds = [
        "intro",
        "verse",
        "build",
        "drop",
        "breakdown",
        "verse",
        "build",
        "drop",
        "breakdown",
        "outro",
    ]
    energy_hint_by_kind = {
        "intro": 4,
        "verse": 5,
        "build": 6,
        "drop": 8,
        "breakdown": 4,
        "outro": 3,
    }
    label_by_kind = {
        "intro": "Auto Intro",
        "verse": "Auto Groove",
        "build": "Auto Build",
        "drop": "Auto Drop",
        "breakdown": "Auto Breakdown",
        "outro": "Auto Outro",
    }

    indices = [
        round(index * (len(template_kinds) - 1) / max(1, target_count - 1))
        for index in range(target_count)
    ]
    phrase_length = duration / target_count
    markers: list[dict[str, Any]] = []
    for index, template_index in enumerate(indices):
        kind = template_kinds[template_index]
        markers.append(
            {
                "name": f"{label_by_kind[kind]} {index + 1}",
                "kind": kind,
                "start_seconds": round(index * phrase_length, 3),
                "energy_hint": energy_hint_by_kind[kind],
            }
        )
    if markers:
        markers[0]["name"] = "Auto Intro"
        markers[-1]["kind"] = "outro"
        markers[-1]["name"] = "Auto Outro"
        markers[-1]["energy_hint"] = energy_hint_by_kind["outro"]
    return markers


def _creative_profile(track_seed: str | None, markers: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    names = sorted(_CREATIVE_PROFILES)
    marker_signature = "|".join(
        f"{marker.get('kind','?')}@{round(float(marker.get('start_seconds', 0.0)), 1)}"
        for marker in markers
    )
    digest = _stable_digest(f"{track_seed or 'unknown'}::{marker_signature}")
    profile_name = names[int.from_bytes(digest[:2], 'big') % len(names)]
    return profile_name, _CREATIVE_PROFILES[profile_name]


def _transition_context(
    *,
    previous_kind: str | None,
    kind: str,
    next_kind: str | None,
    ordinal: int,
    total_of_kind: int,
) -> str:
    stage = pattern_stage(kind)
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


def _model_payload_candidates(
    *,
    family: str,
    kind: str,
    context: str,
    profile: dict[str, Any],
    selected_pattern: str = "",
) -> list[str]:
    candidates = pattern_candidates(
        family=family,
        kind=kind,
        context=context,
        profile=profile,
    )
    limited = list(candidates[:_OLLAMA_CPU_MAX_CANDIDATES])
    if selected_pattern and selected_pattern not in limited and selected_pattern in candidates:
        limited.append(selected_pattern)
    return limited


def build_catalog_model_payload(
    *,
    track_key: str,
    track_title: str,
    track_artist: str,
    duration_seconds: float,
    structure_markers: list[dict[str, Any]],
    show_sections: list[dict[str, Any]],
    selection_mode: str,
    selection_variance: float,
    venue_mode: str,
    rekordbox_track_id: str = "",
    rekordbox_average_bpm: float | None = None,
    semantic_profile: dict[str, Any] | None = None,
    metadata_confidence: dict[str, Any] | None = None,
    web_enrichment: dict[str, Any] | None = None,
    motif_registry: dict[str, Any] | None = None,
    show_fingerprint: dict[str, Any] | None = None,
    anti_template_validation: dict[str, Any] | None = None,
    scorer_bundle: dict[str, Any] | None = None,
    preview_artifacts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    venue_mode = _normalize_venue_mode(venue_mode)
    venue_profile = _venue_profile(venue_mode)
    markers = (
        sorted([dict(marker) for marker in structure_markers], key=lambda item: float(item.get("start_seconds", 0.0)))
        if structure_markers
        else _auto_markers_for_duration(duration_seconds)
    )
    profile_name, profile = _creative_profile(track_key, markers)
    total_counts: dict[str, int] = {}
    for marker in markers:
        marker_kind = str(marker.get("kind") or "marker")
        total_counts[marker_kind] = total_counts.get(marker_kind, 0) + 1

    web_summary = copy.deepcopy((web_enrichment or {}).get("summary", {}))
    web_confidence = copy.deepcopy((web_enrichment or {}).get("confidence", {}))

    payload_sections: list[dict[str, Any]] = []
    previous_selected: dict[str, str] | None = None
    kind_counts: dict[str, int] = {}
    for index, marker in enumerate(markers):
        kind = str(marker.get("kind") or "marker")
        ordinal = kind_counts.get(kind, 0)
        kind_counts[kind] = ordinal + 1
        previous_kind = str(markers[index - 1].get("kind")) if index > 0 else ""
        next_kind = str(markers[index + 1].get("kind")) if index + 1 < len(markers) else ""
        context = _transition_context(
            previous_kind=previous_kind or None,
            kind=kind,
            next_kind=next_kind or None,
            ordinal=ordinal,
            total_of_kind=total_counts.get(kind, 1),
        )
        energy_hint = marker.get("energy_hint")
        energy_scale = max(0.25, min(1.0, float(energy_hint or 6) / 8.0))
        section = dict(show_sections[index]) if index < len(show_sections) else {}
        selected = {
            "laser": str(section.get("laser_pattern") or ""),
            "mover": str(section.get("mover_pattern") or ""),
            "wash": str(section.get("wash_pattern") or ""),
            "led": str(section.get("led_pattern") or ""),
        }
        candidates = {
            family: _model_payload_candidates(
                family=family,
                kind=kind,
                context=context,
                profile=profile,
                selected_pattern=selected[family],
            )
            for family in ("laser", "mover", "wash", "led")
        }
        payload_sections.append(
            {
                "id": str(section.get("id") or f"section_{index:03d}"),
                "label": str(marker.get("name") or section.get("label") or f"Section {index + 1}"),
                "kind": kind,
                "stage": pattern_stage(kind),
                "section_role": str(section.get("section_role") or ""),
                "venue_mode": str(section.get("venue_mode") or venue_mode),
                "cue_family_id": str(section.get("cue_family_id") or ""),
                "lead_family": str(section.get("lead_family") or ""),
                "capability_notes": list(section.get("capability_notes") or []),
                "motif_ids": list(section.get("motif_ids") or []),
                "motif_primary": str(section.get("motif_primary") or ""),
                "start_seconds": round(float(marker.get("start_seconds") or section.get("start_seconds") or 0.0), 3),
                "end_seconds": round(float(section.get("end_seconds") or duration_seconds), 3),
                "length_seconds": round(
                    max(
                        0.0,
                        float(section.get("end_seconds") or duration_seconds)
                        - float(marker.get("start_seconds") or section.get("start_seconds") or 0.0),
                    ),
                    3,
                ),
                "energy_hint": int(energy_hint) if energy_hint is not None else None,
                "energy_scale": round(energy_scale, 3),
                "ordinal_of_kind": ordinal + 1,
                "total_of_kind": total_counts.get(kind, 1),
                "previous_kind": previous_kind,
                "next_kind": next_kind,
                "transition_context": context,
                "transition_intent": copy.deepcopy(section.get("transition_intent", {})),
                "trigger_policy": copy.deepcopy(section.get("cue_recipe", {}).get("trigger_policy", {})),
                "fixture_role_map": copy.deepcopy(section.get("fixture_role_map", {})),
                "fixture_capability_graph": copy.deepcopy(section.get("fixture_capability_graph", {})),
                "recipe_bundle": copy.deepcopy(section.get("cue_recipe", {}).get("recipe_bundle", {})),
                "phaser_bundle": copy.deepcopy(section.get("cue_recipe", {}).get("phaser_bundle", [])),
                "current_selection": selected,
                "previous_selection": copy.deepcopy(previous_selected) if previous_selected else {},
                "candidates": candidates,
            }
        )
        previous_selected = selected

    return {
        "version": 1,
        "track": {
            "track_key": track_key,
            "title": track_title,
            "artist": track_artist,
            "duration_seconds": round(float(duration_seconds), 3),
            "average_bpm": rekordbox_average_bpm,
            "rekordbox_track_id": rekordbox_track_id,
            "selection_mode": selection_mode,
            "selection_variance": selection_variance,
            "venue_mode": venue_mode,
        },
        "planner": {
            "creative_profile": profile_name,
            "energy_profile": str(profile.get("energy_profile") or ""),
            "semantic_profile": copy.deepcopy(semantic_profile or {}),
            "metadata_confidence": copy.deepcopy(metadata_confidence or {}),
            "venue_profile": venue_profile,
            "motif_registry": copy.deepcopy(motif_registry or {}),
            "show_fingerprint": copy.deepcopy(show_fingerprint or {}),
            "anti_template_validation": copy.deepcopy(anti_template_validation or {}),
            "scorer_bundle": copy.deepcopy(scorer_bundle or {}),
            "preview_artifacts": copy.deepcopy(preview_artifacts or {}),
            "style_bias": copy.deepcopy(web_summary.get("style_bias", {})),
            "genre_primary": str(web_summary.get("genre_primary") or ""),
            "genre_secondary": list(web_summary.get("genre_secondary") or []),
            "editorial_descriptors": list(web_summary.get("editorial_descriptors") or []),
            "tags": list(web_summary.get("tags") or []),
            "web_confidence": copy.deepcopy(web_confidence),
        },
        "sections": payload_sections,
    }
