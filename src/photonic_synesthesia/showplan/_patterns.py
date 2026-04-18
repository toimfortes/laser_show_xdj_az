"""Internal leaf: pattern pool constants and per-family selection primitives.

This module is an implementation detail of `showplan.selection` and is duplicated
from the CLI's pattern tables. Keeping it inside showplan avoids reverse-importing
`photonic_synesthesia.ui.cli` while preserving byte-for-byte selection behaviour.
"""

from __future__ import annotations

import json
import logging
import math
import os
import urllib.error as urllib_error
import urllib.request as urllib_request
from hashlib import sha1
from typing import Any

from photonic_synesthesia.showplan.types import (
    clamp as _clamp,
    pattern_stage,
)

_logger = logging.getLogger(__name__)

SELECTION_MODES = {"procedural", "ai_assisted", "local_ollama_cpu"}

OLLAMA_CPU_MODEL = "qwen2.5:1.5b"
OLLAMA_DEFAULT_HOST = "http://127.0.0.1:11434"
OLLAMA_CPU_KEEP_ALIVE = "10m"
OLLAMA_CPU_TIMEOUT_SECONDS = 6.0
OLLAMA_CPU_MAX_CANDIDATES = 6


LASER_PATTERN_POOLS: dict[str, list[str]] = {
    "intro": [
        "fan",
        "beam_fan_narrow",
        "thin_scan",
        "wave",
        "liquid_sky",
        "circle_trace",
        "pentagon_trace",
        "wave_trace",
    ],
    "build": [
        "vertical_rake",
        "horizontal_rake",
        "cone",
        "wave",
        "rotor",
        "liquid_sky",
        "scan_slice",
        "spiral_tunnel",
        "target_step_chase",
        "target_split_chase",
        "loop_trace",
    ],
    "drop": [
        "burst_fan",
        "tunnel",
        "crisscross",
        "starburst",
        "shutter_hits",
        "alternating_beam_groups",
        "beam_fan_wide",
        "split_zone_beams",
        "point_array",
        "spoke_wheel",
        "target_rotate_chase",
        "target_ring_chase",
        "beam_sequence_counterclockwise",
        "mixed_beam_fx",
        "sheet",
    ],
    "breakdown": [
        "thin_scan",
        "liquid_sky",
        "fan",
        "wave",
        "cone",
        "circle_trace",
        "square_trace",
        "spirograph",
        "helix",
        "target_bounce_chase",
    ],
    "outro": [
        "fan",
        "beam_fan_narrow",
        "tri_beam",
        "thin_scan",
        "wave",
        "liquid_sky",
        "horizontal_line_trace",
        "beam_sequence_clockwise",
    ],
}

MOVER_PATTERN_POOLS: dict[str, list[str]] = {
    "intro": ["drift", "circle", "figure_eight", "leaf", "hold"],
    "build": ["rise", "circle", "figure_eight", "mirror_fan", "line_bounce"],
    "drop": ["cross_sweep", "snap_hits", "ping_pong_tilt", "square", "diamond", "mirror_fan"],
    "breakdown": ["hold", "drift", "leaf", "circle"],
    "outro": ["drift", "hold", "line_bounce"],
}

WASH_PATTERN_POOLS: dict[str, list[str]] = {
    "intro": ["ambient", "breath", "gradient_roll", "center_out"],
    "build": ["bloom", "build_ramp", "center_out", "outside_in", "gradient_roll"],
    "drop": ["punch", "downbeat_hit", "white_peak", "drop_slam"],
    "breakdown": ["ambient", "breakdown_glow", "fade", "breath"],
    "outro": ["fade", "ambient", "breath"],
}

LED_PATTERN_POOLS: dict[str, list[str]] = {
    "intro": ["pulse", "sparkle", "horizontal_lines", "fade", "horizontal_ramp"],
    "build": ["ramp", "vertical_build", "vertical_offset", "snake", "rotating_line"],
    "drop": ["chase", "rotating_line", "audio_spectrum", "fizzle", "snake"],
    "breakdown": ["sparkle", "pulse", "fade"],
    "outro": ["fade", "horizontal_ramp", "pulse"],
}

TRANSITION_PATTERN_HINTS: dict[str, dict[str, list[str]]] = {
    "build_riser": {
        "laser": ["vertical_rake", "horizontal_rake", "rotor", "cone", "scan_slice", "target_step_chase", "spiral_tunnel"],
        "mover": ["rise", "mirror_fan", "figure_eight"],
        "wash": ["build_ramp", "bloom", "outside_in"],
        "led": ["vertical_build", "ramp", "vertical_offset"],
    },
    "build_cycle": {
        "laser": ["vertical_rake", "horizontal_rake", "cone", "wave", "rotor", "spiral_tunnel", "target_split_chase", "loop_trace"],
        "mover": ["figure_eight", "circle", "mirror_fan"],
        "wash": ["bloom", "build_ramp", "center_out"],
        "led": ["ramp", "vertical_build", "snake"],
    },
    "drop_launch": {
        "laser": ["shutter_hits", "burst_fan", "starburst", "alternating_beam_groups", "split_zone_beams", "beam_fan_wide", "target_rotate_chase", "point_array"],
        "mover": ["snap_hits", "cross_sweep", "ping_pong_tilt"],
        "wash": ["drop_slam", "white_peak", "downbeat_hit"],
        "led": ["chase", "fizzle", "audio_spectrum"],
    },
    "drop_variation": {
        "laser": ["tunnel", "crisscross", "burst_fan", "alternating_beam_groups", "spiral_tunnel", "sheet", "target_ring_chase", "beam_sequence_counterclockwise"],
        "mover": ["square", "diamond", "cross_sweep", "ping_pong_tilt"],
        "wash": ["white_peak", "punch", "drop_slam"],
        "led": ["rotating_line", "snake", "audio_spectrum", "chase"],
    },
    "breakdown_release": {
        "laser": ["thin_scan", "liquid_sky", "fan", "circle_trace", "spirograph", "target_bounce_chase"],
        "mover": ["hold", "leaf", "drift"],
        "wash": ["breakdown_glow", "fade", "ambient"],
        "led": ["sparkle", "fade", "pulse"],
    },
    "intro_set": {
        "laser": ["fan", "beam_fan_narrow", "thin_scan", "wave", "circle_trace", "liquid_sky"],
        "mover": ["drift", "circle", "leaf"],
        "wash": ["ambient", "breath", "center_out"],
        "led": ["pulse", "fade", "horizontal_lines"],
    },
    "outro_release": {
        "laser": ["fan", "beam_fan_narrow", "thin_scan", "wave", "horizontal_line_trace", "liquid_sky"],
        "mover": ["hold", "drift", "line_bounce"],
        "wash": ["fade", "ambient", "breath"],
        "led": ["fade", "horizontal_ramp", "pulse"],
    },
}

LASER_PATTERN_GEOMETRY: dict[str, str] = {
    "fan": "fan",
    "beam_fan_narrow": "fan",
    "beam_fan_wide": "fan",
    "cross_room_fans": "fan",
    "thin_scan": "scan",
    "scan_slice": "scan",
    "wave": "scan",
    "vertical_rake": "rake",
    "horizontal_rake": "rake",
    "liquid_sky": "sky",
    "cone": "cone",
    "tunnel": "tunnel",
    "spiral_tunnel": "tunnel",
    "crisscross": "lattice",
    "lattice": "lattice",
    "rotor": "helix",
    "helix": "helix",
    "spirograph": "helix",
    "wave_trace": "helix",
    "loop_trace": "helix",
    "roll_trace": "helix",
    "burst_fan": "burst",
    "starburst": "burst",
    "shutter_hits": "burst",
    "mixed_beam_fx": "burst",
    "alternating_beam_groups": "grouped",
    "split_zone_beams": "grouped",
    "target_split_chase": "grouped",
    "static_beam": "array",
    "dual_beam": "array",
    "tri_beam": "array",
    "point_array": "array",
    "spoke_wheel": "array",
    "sheet": "sheet",
    "circle_trace": "trace",
    "vertical_line_trace": "trace",
    "horizontal_line_trace": "trace",
    "triangle_trace": "trace",
    "square_trace": "trace",
    "pentagon_trace": "trace",
    "hexagon_trace": "trace",
    "target_step_chase": "sequence",
    "target_bounce_chase": "sequence",
    "target_rotate_chase": "sequence",
    "target_ring_chase": "sequence",
    "beam_sequence_clockwise": "sequence",
    "beam_sequence_counterclockwise": "sequence",
}


def normalize_selection_mode(selection_mode: str | None) -> str:
    value = str(selection_mode or "procedural").strip().lower().replace("-", "_")
    return value if value in SELECTION_MODES else "procedural"


def normalize_selection_variance(value: Any | None) -> float:
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return 0.0
    return round(_clamp(normalized, 0.0, 1.0), 3)


def _stable_digest(label: str) -> bytes:
    return sha1(label.encode()).digest()


def _stable_float(label: str) -> float:
    return int.from_bytes(_stable_digest(label)[:8], "big") / float(2 ** 64)


def _stable_seed(token: str) -> int:
    return int.from_bytes(_stable_digest(token)[:4], "big") & 0x7FFFFFFF


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def pattern_candidates(
    *,
    family: str,
    kind: str,
    context: str,
    profile: dict[str, Any],
) -> list[str]:
    stage = pattern_stage(kind)
    pools = {
        "laser": LASER_PATTERN_POOLS,
        "mover": MOVER_PATTERN_POOLS,
        "wash": WASH_PATTERN_POOLS,
        "led": LED_PATTERN_POOLS,
    }
    base_candidates = list(pools[family].get(stage) or pools[family]["intro"])
    profile_candidates = list(profile.get("patterns", {}).get(family, {}).get(stage, []))
    transition_candidates = list(TRANSITION_PATTERN_HINTS.get(context, {}).get(family, []))
    return _dedupe(transition_candidates + profile_candidates + base_candidates)


def _semantic_tokens(semantic_profile: dict[str, Any] | None) -> set[str]:
    if not isinstance(semantic_profile, dict):
        return set()
    tokens: set[str] = set()
    for value in semantic_profile.get("genre_hints", []):
        text = str(value).strip().lower()
        if text:
            tokens.add(text)
    for value in semantic_profile.get("descriptors", []):
        text = str(value).strip().lower()
        if text:
            tokens.add(text)
    return tokens


def _semantic_style_bias(semantic_profile: dict[str, Any] | None, key: str) -> float:
    if not isinstance(semantic_profile, dict):
        return 0.0
    style_bias = semantic_profile.get("style_bias", {})
    if not isinstance(style_bias, dict):
        return 0.0
    try:
        return float(style_bias.get(key, 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _semantic_pattern_score_bonus(
    *,
    family: str,
    stage: str,
    context: str,
    candidate: str,
    energy_scale: float,
    semantic_profile: dict[str, Any] | None,
) -> float:
    tokens = _semantic_tokens(semantic_profile)
    if not tokens:
        return 0.0

    progressive = any("progressive house" in token for token in tokens)
    melodic = any("melodic house" in token for token in tokens)
    patience = _semantic_style_bias(semantic_profile, "progressive_patience")
    aggression = _semantic_style_bias(semantic_profile, "drop_aggression")
    atmosphere = _semantic_style_bias(semantic_profile, "atmosphere")

    score = 0.0
    if family == "laser":
        if stage in {"intro", "breakdown", "outro"}:
            if candidate in {"thin_scan", "wave", "liquid_sky", "circle_trace", "fan", "horizontal_line_trace", "spirograph", "helix"}:
                score += 0.22
            if candidate in {"shutter_hits", "burst_fan", "starburst", "point_array", "mixed_beam_fx", "beam_sequence_counterclockwise"}:
                score -= 0.36
        elif stage == "build":
            if candidate in {"horizontal_rake", "scan_slice", "cone", "spiral_tunnel", "wave", "rotor"}:
                score += 0.18
            if candidate in {"target_step_chase", "target_split_chase"} and progressive:
                score -= 0.14
        elif stage == "drop":
            if progressive or melodic:
                if candidate in {"spiral_tunnel", "tunnel", "sheet", "crisscross", "alternating_beam_groups", "spoke_wheel", "mixed_beam_fx"}:
                    score += 0.24
                if candidate in {"starburst", "point_array", "shutter_hits", "beam_sequence_counterclockwise"}:
                    score -= 0.24
        if progressive:
            if stage in {"intro", "breakdown"} and candidate in {"wave", "thin_scan", "horizontal_line_trace"}:
                score += 0.06
            if stage == "drop" and candidate in {"tunnel", "crisscross", "spoke_wheel"}:
                score += 0.08
        if melodic:
            if stage in {"intro", "breakdown"} and candidate in {"helix", "spirograph", "circle_trace"}:
                score += 0.06
            if stage == "build" and candidate in {"cone", "spiral_tunnel", "rotor"}:
                score += 0.08
            if stage == "drop" and candidate in {"mixed_beam_fx", "sheet", "spiral_tunnel", "alternating_beam_groups"}:
                score += 0.08
    elif family == "mover":
        if stage in {"intro", "breakdown", "outro"}:
            if candidate in {"drift", "circle", "hold", "leaf"}:
                score += 0.18
            if candidate in {"snap_hits", "square", "diamond"}:
                score -= 0.22
        elif stage == "drop":
            if candidate in {"cross_sweep", "mirror_fan", "diamond", "ping_pong_tilt"}:
                score += 0.16
            if candidate == "snap_hits" and (progressive or melodic):
                score -= 0.22
        if progressive and candidate in {"drift", "circle", "cross_sweep"}:
            score += 0.04
        if melodic and candidate in {"mirror_fan", "diamond", "figure_eight"}:
            score += 0.06
    elif family == "wash":
        if stage in {"intro", "breakdown", "outro"}:
            if candidate in {"ambient", "breath", "gradient_roll", "fade"}:
                score += 0.16
            if candidate in {"drop_slam", "punch", "white_peak"}:
                score -= 0.28
        elif stage == "build":
            if candidate in {"bloom", "build_ramp", "center_out", "gradient_roll"}:
                score += 0.14
        elif stage == "drop":
            if candidate in {"downbeat_hit", "white_peak", "punch"}:
                score += 0.12
            if candidate == "drop_slam" and (progressive or melodic):
                score -= 0.28
        if progressive and candidate in {"breath", "gradient_roll", "white_peak"}:
            score += 0.04
        if melodic and candidate in {"center_out", "bloom", "downbeat_hit"}:
            score += 0.05
    elif family == "led":
        if stage in {"intro", "breakdown", "outro"}:
            if candidate in {"fade", "pulse", "horizontal_lines", "sparkle", "horizontal_ramp"}:
                score += 0.14
            if candidate in {"snake", "audio_spectrum", "chase"}:
                score -= 0.18
        elif stage == "build":
            if candidate in {"vertical_build", "vertical_offset", "rotating_line"}:
                score += 0.14
        elif stage == "drop":
            if candidate in {"chase", "rotating_line", "audio_spectrum"}:
                score += 0.14
            if candidate == "snake" and (progressive or melodic):
                score -= 0.18
        if progressive and candidate in {"fade", "rotating_line"}:
            score += 0.04
        if melodic and candidate in {"audio_spectrum", "vertical_offset", "sparkle"}:
            score += 0.05

    if patience >= 0.7 and stage in {"intro", "breakdown"} and energy_scale <= 0.6:
        if family == "laser" and candidate in {"thin_scan", "wave", "liquid_sky", "circle_trace", "fan"}:
            score += 0.08
        if family == "wash" and candidate in {"ambient", "breath", "fade"}:
            score += 0.06
    if aggression <= 0.45 and context == "drop_launch":
        if candidate in {"drop_slam", "snap_hits", "starburst", "point_array"}:
            score -= 0.18
    if atmosphere >= 0.7 and stage in {"breakdown", "outro"}:
        if family == "laser" and candidate in {"liquid_sky", "spirograph", "helix", "circle_trace"}:
            score += 0.08
        if family == "mover" and candidate in {"drift", "leaf", "hold"}:
            score += 0.06
    return score


def _ai_assisted_pattern_score(
    *,
    family: str,
    kind: str,
    context: str,
    track_seed: str,
    marker_name: str,
    ordinal: int,
    energy_scale: float,
    candidate: str,
    candidates: list[str],
    previous_pattern: str | None,
    recent_patterns: list[str] | None = None,
    usage_count: int = 0,
    semantic_profile: dict[str, Any] | None = None,
) -> float:
    stage = pattern_stage(kind)
    candidate_index = candidates.index(candidate)
    score = max(0.0, 1.9 - candidate_index * 0.16)
    score += (_stable_float(f"{track_seed}:{family}:{kind}:{context}:{ordinal}:{marker_name}:{candidate}") - 0.5) * 0.44

    if candidate == previous_pattern:
        score -= 1.5
    if usage_count > 0:
        score -= min(0.9, usage_count * 0.28)
    if recent_patterns:
        recent_hits = sum(1 for value in recent_patterns if value == candidate)
        score -= recent_hits * 0.22

    score += _semantic_pattern_score_bonus(
        family=family,
        stage=stage,
        context=context,
        candidate=candidate,
        energy_scale=energy_scale,
        semantic_profile=semantic_profile,
    )

    if family == "laser":
        geometry = LASER_PATTERN_GEOMETRY.get(candidate, "fan")
        stage_geometry_weights = {
            "intro": {"trace": 0.5, "sky": 0.42, "fan": 0.28, "scan": 0.24, "cone": 0.16, "array": -0.48, "sequence": -0.42, "burst": -0.32},
            "build": {"rake": 0.5, "sequence": 0.36, "scan": 0.3, "tunnel": 0.28, "cone": 0.22, "helix": 0.16, "array": -0.18},
            "drop": {"burst": 0.52, "grouped": 0.44, "tunnel": 0.38, "lattice": 0.34, "sheet": 0.3, "fan": 0.22, "trace": -0.34, "sky": -0.26},
            "breakdown": {"sky": 0.54, "trace": 0.46, "helix": 0.34, "fan": 0.22, "scan": 0.16, "burst": -0.46, "grouped": -0.32},
            "outro": {"trace": 0.44, "fan": 0.3, "sky": 0.26, "scan": 0.16, "array": 0.08, "burst": -0.36, "grouped": -0.26},
        }
        context_geometry_weights = {
            "build_riser": {"rake": 0.5, "sequence": 0.28, "scan": 0.24, "tunnel": 0.18},
            "build_cycle": {"helix": 0.28, "trace": 0.24, "cone": 0.2, "scan": 0.14, "rake": 0.12},
            "drop_launch": {"burst": 0.56, "grouped": 0.4, "fan": 0.24, "sheet": 0.14},
            "drop_variation": {"tunnel": 0.44, "lattice": 0.34, "sheet": 0.28, "sequence": 0.2},
            "breakdown_release": {"sky": 0.36, "trace": 0.32, "fan": 0.18, "helix": 0.12},
            "intro_set": {"trace": 0.26, "fan": 0.18, "sky": 0.16},
            "outro_release": {"trace": 0.22, "fan": 0.18, "sky": 0.14},
        }
        score += stage_geometry_weights.get(stage, {}).get(geometry, 0.0)
        score += context_geometry_weights.get(context, {}).get(geometry, 0.0)

        if energy_scale >= 0.82 and geometry in {"burst", "grouped", "tunnel", "lattice", "sequence", "sheet"}:
            score += 0.24
        elif energy_scale <= 0.55 and geometry in {"fan", "scan", "sky", "trace", "cone", "helix"}:
            score += 0.2

        previous_geometry = LASER_PATTERN_GEOMETRY.get(previous_pattern or "", "")
        if previous_geometry and previous_geometry == geometry:
            score -= 0.24

    return score


def _stable_weighted_choice(
    *,
    token: str,
    weighted_candidates: list[tuple[str, float]],
) -> str:
    if not weighted_candidates:
        raise RuntimeError("No weighted candidates available")
    total_weight = sum(max(0.0, weight) for _, weight in weighted_candidates)
    if total_weight <= 0:
        return weighted_candidates[0][0]
    threshold = _stable_float(token) * total_weight
    cumulative = 0.0
    for candidate, weight in weighted_candidates:
        cumulative += max(0.0, weight)
        if threshold <= cumulative:
            return candidate
    return weighted_candidates[-1][0]


def _candidate_priority(
    *,
    family: str,
    kind: str,
    context: str,
    profile: dict[str, Any],
    track_seed: str,
    marker_name: str,
    ordinal: int,
    energy_scale: float,
    previous_pattern: str | None,
    recent_patterns: list[str] | None = None,
    usage_count_by_pattern: dict[str, int] | None = None,
    semantic_profile: dict[str, Any] | None = None,
) -> list[str]:
    candidates = pattern_candidates(family=family, kind=kind, context=context, profile=profile)
    if not candidates:
        return []
    scored_candidates: list[tuple[str, float]] = []
    for candidate in candidates:
        score = _ai_assisted_pattern_score(
            family=family,
            kind=kind,
            context=context,
            track_seed=track_seed,
            marker_name=marker_name,
            ordinal=ordinal,
            energy_scale=energy_scale,
            candidate=candidate,
            candidates=candidates,
            previous_pattern=previous_pattern,
            recent_patterns=recent_patterns,
            usage_count=(usage_count_by_pattern or {}).get(candidate, 0),
            semantic_profile=semantic_profile,
        )
        scored_candidates.append((candidate, score))
    scored_candidates.sort(key=lambda item: item[1], reverse=True)
    return [candidate for candidate, _ in scored_candidates]


def _ollama_stage_direction(kind: str, context: str, energy_scale: float) -> str:
    stage = pattern_stage(kind)
    stage_prompt = {
        "intro": "spacious opener, patient evolution, low impact",
        "build": "escalating tension, motion growth, hold back the peak",
        "drop": "impact, contrast, clear hook, synchronized hit energy",
        "breakdown": "restraint, atmosphere, melodic space, reduced aggression",
        "outro": "release, tapering motion, graceful exit",
    }[stage]
    if context == "build_riser":
        stage_prompt += "; emphasize lift"
    elif context == "drop_launch":
        stage_prompt += "; emphasize punch"
    elif context == "drop_variation":
        stage_prompt += "; vary from the previous drop"
    elif context == "breakdown_release":
        stage_prompt += "; keep it soft and wide"
    return f"{stage_prompt}; energy {energy_scale:.2f}"


def _coerce_json_object(raw_response: str) -> dict[str, Any] | None:
    payload = str(raw_response or "").strip()
    if not payload:
        return None
    if "```" in payload:
        payload = payload.replace("```json", "```")
        fence_parts = [part.strip() for part in payload.split("```") if part.strip()]
        if fence_parts:
            payload = fence_parts[0]
    start = payload.find("{")
    end = payload.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        parsed = json.loads(payload[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _default_ollama_model_name() -> str:
    return str(os.environ.get("PHOTONIC_OLLAMA_MODEL") or OLLAMA_CPU_MODEL).strip() or OLLAMA_CPU_MODEL


def _default_ollama_generate_endpoint() -> str:
    host = str(os.environ.get("PHOTONIC_OLLAMA_HOST") or os.environ.get("OLLAMA_HOST") or OLLAMA_DEFAULT_HOST).strip() or OLLAMA_DEFAULT_HOST
    host = host.rstrip("/")
    if not host.startswith("http://") and not host.startswith("https://"):
        host = f"http://{host}"
    return f"{host}/api/generate"


def _default_ollama_num_gpu_option() -> int | None:
    value = os.environ.get("PHOTONIC_OLLAMA_NUM_GPU")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def ollama_section_selection(
    *,
    kind: str,
    context: str,
    profile: dict[str, Any],
    track_seed: str,
    marker_name: str,
    ordinal: int,
    energy_scale: float,
    previous_patterns: dict[str, str | None],
    pattern_history: dict[str, list[str]] | None,
    usage_count_by_family: dict[str, dict[str, int]] | None,
    semantic_profile: dict[str, Any] | None,
    selection_variance: float,
    ollama_model_name_fn=None,
    ollama_generate_endpoint_fn=None,
    ollama_num_gpu_option_fn=None,
) -> dict[str, str] | None:
    _ollama_model_name = ollama_model_name_fn or _default_ollama_model_name
    _ollama_generate_endpoint = ollama_generate_endpoint_fn or _default_ollama_generate_endpoint
    _ollama_num_gpu_option = ollama_num_gpu_option_fn or _default_ollama_num_gpu_option

    selection_variance = normalize_selection_variance(selection_variance)
    family_candidates: dict[str, list[str]] = {}
    for family in ("laser", "mover", "wash", "led"):
        ranked = _candidate_priority(
            family=family,
            kind=kind,
            context=context,
            profile=profile,
            track_seed=track_seed,
            marker_name=marker_name,
            ordinal=ordinal,
            energy_scale=energy_scale,
            previous_pattern=previous_patterns.get(family),
            recent_patterns=(pattern_history or {}).get(family, [])[-4:],
            usage_count_by_pattern=(usage_count_by_family or {}).get(family, {}),
            semantic_profile=semantic_profile,
        )
        limited = ranked[:OLLAMA_CPU_MAX_CANDIDATES]
        if not limited:
            return None
        family_candidates[family] = limited

    prompt_lines = [
        "Pick one coordinated lighting pattern per family.",
        f"Section: {kind}",
        f"Context: {context}",
        f"Marker: {marker_name}",
        f"Direction: {_ollama_stage_direction(kind, context, energy_scale)}",
        f"Exploration: {selection_variance:.2f}",
        f"Profile: {profile.get('label', 'dynamic')}",
        "Previous:"
        f" laser={previous_patterns.get('laser') or 'none'}"
        f", mover={previous_patterns.get('mover') or 'none'}"
        f", wash={previous_patterns.get('wash') or 'none'}"
        f", led={previous_patterns.get('led') or 'none'}",
        "Rules:",
        "- Choose exactly one option from each family list.",
        "- Keep movers complementary to the laser choice.",
        "- Respect the section role: intros spacious, builds rising, drops impactful, breakdowns restrained, outros releasing.",
        "- Prefer contrast against repeated previous choices when it still fits the section.",
        f"laser: {', '.join(family_candidates['laser'])}",
        f"mover: {', '.join(family_candidates['mover'])}",
        f"wash: {', '.join(family_candidates['wash'])}",
        f"led: {', '.join(family_candidates['led'])}",
        'Return JSON only: {"laser":"...","mover":"...","wash":"...","led":"..."}',
    ]
    options: dict[str, Any] = {
        "seed": _stable_seed(f"{track_seed}:{kind}:{context}:{ordinal}:{marker_name}:{selection_variance}"),
        "temperature": round(selection_variance * 0.55, 3),
        "top_p": round(0.25 + selection_variance * 0.55, 3),
        "num_predict": 120,
    }
    ollama_num_gpu = _ollama_num_gpu_option()
    if ollama_num_gpu is not None:
        options["num_gpu"] = ollama_num_gpu

    payload = {
        "model": _ollama_model_name(),
        "prompt": "\n".join(prompt_lines),
        "stream": False,
        "format": "json",
        "keep_alive": OLLAMA_CPU_KEEP_ALIVE,
        "options": options,
    }
    request = urllib_request.Request(
        _ollama_generate_endpoint(),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(request, timeout=OLLAMA_CPU_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib_error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        _logger.warning(f"Local Ollama CPU selection failed: {exc}")
        return None

    parsed = _coerce_json_object(body.get("response", ""))
    if parsed is None:
        _logger.warning("Local Ollama CPU selection returned invalid JSON")
        return None

    resolved: dict[str, str] = {}
    for family in ("laser", "mover", "wash", "led"):
        candidate = str(parsed.get(family, "")).strip()
        if candidate in family_candidates[family]:
            resolved[family] = candidate
    return resolved if resolved else None


def select_pattern(
    *,
    family: str,
    kind: str,
    context: str,
    profile: dict[str, Any],
    track_seed: str,
    marker_name: str,
    ordinal: int,
    previous_pattern: str | None,
    recent_patterns: list[str] | None = None,
    usage_count_by_pattern: dict[str, int] | None = None,
    semantic_profile: dict[str, Any] | None = None,
    selection_mode: str = "procedural",
    energy_scale: float = 0.6,
    selection_variance: float = 0.0,
) -> str:
    candidates = pattern_candidates(family=family, kind=kind, context=context, profile=profile)
    if not candidates:
        raise RuntimeError(f"No pattern candidates for {family}:{kind}:{context}")
    if len(candidates) == 1:
        return candidates[0]
    selection_mode = normalize_selection_mode(selection_mode)
    selection_variance = normalize_selection_variance(selection_variance)
    if selection_mode == "ai_assisted":
        scored_candidates: list[tuple[str, float]] = []
        for candidate in candidates:
            score = _ai_assisted_pattern_score(
                family=family,
                kind=kind,
                context=context,
                track_seed=track_seed,
                marker_name=marker_name,
                ordinal=ordinal,
                energy_scale=energy_scale,
                candidate=candidate,
                candidates=candidates,
                previous_pattern=previous_pattern,
                recent_patterns=recent_patterns,
                usage_count=(usage_count_by_pattern or {}).get(candidate, 0),
                semantic_profile=semantic_profile,
            )
            scored_candidates.append((candidate, score))
        scored_candidates.sort(key=lambda item: item[1], reverse=True)
        if selection_variance <= 0:
            return scored_candidates[0][0]
        max_score = scored_candidates[0][1]
        temperature = 0.12 + selection_variance * 1.05
        weighted_candidates = [
            (candidate, math.exp((score - max_score) / max(0.05, temperature)))
            for candidate, score in scored_candidates
        ]
        return _stable_weighted_choice(
            token=f"{track_seed}:{family}:{kind}:{context}:{ordinal}:{marker_name}:ai:{selection_variance}",
            weighted_candidates=weighted_candidates,
        )
    digest = _stable_digest(f"{track_seed}:{family}:{kind}:{context}:{ordinal}:{marker_name}")
    start_index = int.from_bytes(digest[:2], "big") % len(candidates)
    ordered = candidates[start_index:] + candidates[:start_index]
    recent_pattern_set = set(recent_patterns or [])
    usage_counts = usage_count_by_pattern or {}
    ordered_nonrepeat = [candidate for candidate in ordered if candidate != previous_pattern] or ordered
    stage = pattern_stage(kind)
    ordered_nonrepeat.sort(
        key=lambda candidate: (
            -_semantic_pattern_score_bonus(
                family=family,
                stage=stage,
                context=context,
                candidate=candidate,
                energy_scale=energy_scale,
                semantic_profile=semantic_profile,
            ),
            candidate in recent_pattern_set,
            usage_counts.get(candidate, 0),
            ordered.index(candidate),
        )
    )
    if selection_variance <= 0:
        return ordered_nonrepeat[0]
    scale = 0.35 + selection_variance * 1.55
    weighted_candidates = [
        (candidate, math.exp(-(index / scale)))
        for index, candidate in enumerate(ordered_nonrepeat)
    ]
    return _stable_weighted_choice(
        token=f"{track_seed}:{family}:{kind}:{context}:{ordinal}:{marker_name}:procedural:{selection_variance}",
        weighted_candidates=weighted_candidates,
    )
