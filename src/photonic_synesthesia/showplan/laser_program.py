"""Laser program builder for the showplan facade.

Builds a phrase-role laser payload (launch / sustain / fills / release) for a
single section. Constants here are duplicated from the CLI's pattern tables so
this module stays free of `photonic_synesthesia.ui.*` and
`platform.runtime_context*` imports. If these drift from the CLI's copies,
tests will catch it.
"""

from __future__ import annotations

from typing import Any

from photonic_synesthesia.showplan._patterns import (
    LASER_PATTERN_GEOMETRY,
    LASER_PATTERN_POOLS,
    TRANSITION_PATTERN_HINTS,
    _dedupe,
    _stable_digest,
    _stable_float,
    pattern_candidates,
    pattern_stage,
)
from photonic_synesthesia.showplan.types import (
    LASER_PROGRAM_VERSION as _LASER_PROGRAM_VERSION,
    VENUE_MODES as _VENUE_MODES,
    apply_venue_laser_zone_policy as _apply_venue_laser_zone_policy,
    laser_zone_policy as _laser_zone_policy,
    normalize_venue_mode as _normalize_venue_mode,
)

_PHRASE_ENVELOPES: dict[str, dict[str, Any]] = {
    "intro": {
        "launch_bars": 0,
        "sustain_bars": 16,
        "release_bars": 8,
        "normalize_after_bars": 4,
        "intensity_curve": "gentle_ramp",
    },
    "build": {
        "launch_bars": 4,
        "sustain_bars": 8,
        "release_bars": 2,
        "normalize_after_bars": 2,
        "intensity_curve": "escalating_riser",
    },
    "drop": {
        "launch_bars": 4,
        "sustain_bars": 8,
        "release_bars": 4,
        "normalize_after_bars": 4,
        "intensity_curve": "impact_then_settle",
    },
    "breakdown": {
        "launch_bars": 0,
        "sustain_bars": 16,
        "release_bars": 8,
        "normalize_after_bars": 2,
        "intensity_curve": "floating_plateau",
    },
    "outro": {
        "launch_bars": 0,
        "sustain_bars": 8,
        "release_bars": 8,
        "normalize_after_bars": 2,
        "intensity_curve": "progressive_subtraction",
    },
}

_GEOMETRY_STRATEGIES: dict[str, dict[str, str]] = {
    "fan": {
        "content_family": "beam",
        "blanking_strategy": "open_groove",
        "target_strategy": "wide_zone_sweep",
        "color_strategy": "slow_palette_drift",
    },
    "burst": {
        "content_family": "transition",
        "blanking_strategy": "impact_gates",
        "target_strategy": "drop_launch_fan",
        "color_strategy": "white_accent_launch",
    },
    "grouped": {
        "content_family": "beam",
        "blanking_strategy": "alternating_groups",
        "target_strategy": "split_zone_hits",
        "color_strategy": "contrast_flips",
    },
    "tunnel": {
        "content_family": "beam",
        "blanking_strategy": "breathing_aperture",
        "target_strategy": "depth_chase",
        "color_strategy": "center_pull_morph",
    },
    "lattice": {
        "content_family": "beam",
        "blanking_strategy": "cross_cutting",
        "target_strategy": "cross_room_fans",
        "color_strategy": "dual_cycle_contrast",
    },
    "rake": {
        "content_family": "transition",
        "blanking_strategy": "riser_chops",
        "target_strategy": "vertical_pressure",
        "color_strategy": "narrowing_palette",
    },
    "sky": {
        "content_family": "abstract",
        "blanking_strategy": "soft_air",
        "target_strategy": "aerial_hold",
        "color_strategy": "harmonic_morph",
    },
    "cone": {
        "content_family": "abstract",
        "blanking_strategy": "soft_sweep",
        "target_strategy": "ceiling_bloom",
        "color_strategy": "halo_morph",
    },
    "scan": {
        "content_family": "beam",
        "blanking_strategy": "tight_slice",
        "target_strategy": "line_sweep",
        "color_strategy": "single_hue_focus",
    },
    "helix": {
        "content_family": "abstract",
        "blanking_strategy": "rolling_draw",
        "target_strategy": "spiral_air_wrap",
        "color_strategy": "evolving_multicolor",
    },
    "array": {
        "content_family": "beam",
        "blanking_strategy": "point_steps",
        "target_strategy": "center_axis_hold",
        "color_strategy": "target_color_steps",
    },
    "sheet": {
        "content_family": "beam",
        "blanking_strategy": "sheet_open",
        "target_strategy": "sheet_wall",
        "color_strategy": "texture_flip",
    },
    "trace": {
        "content_family": "abstract",
        "blanking_strategy": "shape_draw",
        "target_strategy": "shape_trace",
        "color_strategy": "shape_outline_morph",
    },
    "sequence": {
        "content_family": "transition",
        "blanking_strategy": "point_steps",
        "target_strategy": "sequenced_targets",
        "color_strategy": "target_color_steps",
    },
}


def _pick_word(track_seed: str, token: str, words: list[str]) -> str:
    index = int(_stable_float(f"{track_seed}:{token}") * len(words)) % len(words)
    return words[index]


def _variant_label(
    track_seed: str,
    token: str,
    base_pattern: str,
    adjectives: list[str],
    nouns: list[str],
) -> str:
    adjective = _pick_word(track_seed, f"{token}:adj", adjectives)
    noun = _pick_word(track_seed, f"{token}:noun", nouns)
    base = base_pattern.replace("_", " ").title()
    return f"{adjective} {noun} {base}"


def _laser_color_mode_for_strategy(color_strategy: str, context: str) -> str:
    if color_strategy in {"white_accent_launch"} or context == "drop_launch":
        return "white_hits"
    if color_strategy in {"target_color_steps", "contrast_flips", "texture_flip", "dual_cycle_contrast"}:
        return "dual_cycle"
    if color_strategy in {"single_hue_focus"}:
        return "static"
    return "morph"


def _laser_look(
    *,
    track_seed: str,
    base_pattern: str,
    context: str,
    kind: str,
    ordinal: int,
    token_suffix: str,
) -> dict[str, Any]:
    token = f"laser-look:{kind}:{context}:{ordinal}:{base_pattern}:{token_suffix}"
    geometry_family = LASER_PATTERN_GEOMETRY.get(base_pattern, "fan")
    strategy = _GEOMETRY_STRATEGIES.get(geometry_family, _GEOMETRY_STRATEGIES["fan"])
    target_bias = ["crowd", "mid_air", "ceiling"][int(_stable_float(f"{token}:target_bias") * 3) % 3]
    return {
        "id": f"{token_suffix}_{base_pattern}",
        "label": _variant_label(
            track_seed,
            token,
            base_pattern,
            ["Vector", "Prism", "Arc", "Nova", "Pulse", "Aerial"],
            ["Look", "Pass", "Sweep", "Launch", "Fill", "Shape"],
        ),
        "pattern": base_pattern,
        "geometry_family": geometry_family,
        "content_family": strategy["content_family"],
        "target_strategy": strategy["target_strategy"],
        "blanking_strategy": strategy["blanking_strategy"],
        "color_strategy": strategy["color_strategy"],
        "color_mode": _laser_color_mode_for_strategy(strategy["color_strategy"], context),
        "target_bias": target_bias,
        "density": round(0.72 + _stable_float(f"{token}:density") * 0.95, 3),
        "motion": round(0.7 + _stable_float(f"{token}:motion") * 1.05, 3),
        "emphasis": round(0.3 + _stable_float(f"{token}:emphasis") * 0.7, 3),
        "bars": 4,
    }


def build_laser_program(
    *,
    track_seed: str,
    base_pattern: str,
    kind: str,
    context: str,
    ordinal: int,
    profile: dict[str, Any],
    venue_mode: str,
) -> dict[str, Any]:
    def _rotate_patterns(patterns: list[str], token: str) -> list[str]:
        if len(patterns) <= 1:
            return patterns
        digest = _stable_digest(f"{track_seed}:laser-program:{kind}:{context}:{ordinal}:{token}")
        offset = int.from_bytes(digest[:2], "big") % len(patterns)
        return patterns[offset:] + patterns[:offset]

    stage = pattern_stage(kind)
    all_candidates = pattern_candidates(
        family="laser",
        kind=kind,
        context=context,
        profile=profile,
    )
    release_stage = "breakdown" if stage in {"drop", "build"} else "intro"
    release_candidates = _dedupe(
        list(LASER_PATTERN_POOLS.get(release_stage, LASER_PATTERN_POOLS["intro"]))
        + ["fan", "thin_scan", "circle_trace"]
    )
    fill_hints = TRANSITION_PATTERN_HINTS.get(context, {}).get("laser", [])
    sustain_candidates = _dedupe([base_pattern] + all_candidates)
    fill_candidates = _dedupe(fill_hints + all_candidates[1:])
    phrase_template = _PHRASE_ENVELOPES[stage]

    launch_pattern = base_pattern
    sustain_target_count = 2
    fill_target_count = 2
    distinct_sustain_candidates = _rotate_patterns(
        [pattern for pattern in sustain_candidates if pattern != launch_pattern],
        "sustain",
    )
    if distinct_sustain_candidates:
        sustain_patterns = distinct_sustain_candidates[:sustain_target_count]
    else:
        sustain_patterns = sustain_candidates[:sustain_target_count] if sustain_candidates else [base_pattern]
    used_patterns = {launch_pattern, *sustain_patterns}
    distinct_fill_candidates = _rotate_patterns(
        [pattern for pattern in fill_candidates if pattern not in used_patterns],
        "fills",
    )
    if not distinct_fill_candidates:
        distinct_fill_candidates = _rotate_patterns(
            [pattern for pattern in sustain_candidates if pattern != launch_pattern],
            "fills-fallback",
        )
    fill_patterns = distinct_fill_candidates[:fill_target_count] if distinct_fill_candidates else sustain_patterns[:1]
    release_pattern = release_candidates[int(_stable_float(f"{track_seed}:release:{kind}:{ordinal}") * len(release_candidates)) % len(release_candidates)]

    if stage == "breakdown":
        sustain_patterns = [pattern for pattern in sustain_patterns if LASER_PATTERN_GEOMETRY.get(pattern, "fan") in {"sky", "trace", "helix", "fan", "cone", "scan"}] or sustain_patterns
        fill_patterns = sustain_patterns[:1]
    elif stage == "intro":
        fill_patterns = sustain_patterns[:1]

    while len(sustain_patterns) < sustain_target_count:
        sustain_patterns.append(sustain_patterns[-1] if sustain_patterns else launch_pattern)
    while len(fill_patterns) < fill_target_count:
        fill_patterns.append(fill_patterns[-1] if fill_patterns else sustain_patterns[-1] if sustain_patterns else launch_pattern)

    sustain_bar_budget = max(1, int(phrase_template["sustain_bars"]))
    sustain_bar_base = max(1, sustain_bar_budget // max(1, len(sustain_patterns)))
    sustain_bar_remainder = max(0, sustain_bar_budget - sustain_bar_base * len(sustain_patterns))
    fill_bar_base = 1 if stage in {"build", "drop"} else 2
    fill_cadence = {
        "build_riser": 2,
        "build_cycle": 4,
        "drop_launch": 4,
        "drop_variation": 2,
        "breakdown_release": 8,
        "intro_set": 8,
        "outro_release": 8,
    }.get(context, 4 if stage == "drop" else 6 if stage == "build" else 8)

    launch_look = _laser_look(
        track_seed=track_seed,
        base_pattern=launch_pattern,
        context=context,
        kind=kind,
        ordinal=ordinal,
        token_suffix="launch",
    )
    launch_look["label"] = "Launch Hook"
    launch_look["bars"] = max(0, int(phrase_template["launch_bars"]))

    sustain_looks: list[dict[str, Any]] = []
    for index, pattern in enumerate(sustain_patterns):
        look = _laser_look(
            track_seed=track_seed,
            base_pattern=pattern,
            context=context,
            kind=kind,
            ordinal=ordinal,
            token_suffix=f"sustain_{index}",
        )
        look["label"] = f"Sustain {chr(65 + index)}"
        look["bars"] = sustain_bar_base + (1 if index < sustain_bar_remainder else 0)
        sustain_looks.append(look)

    fill_looks: list[dict[str, Any]] = []
    for index, pattern in enumerate(fill_patterns):
        look = _laser_look(
            track_seed=track_seed,
            base_pattern=pattern,
            context=context,
            kind=kind,
            ordinal=ordinal,
            token_suffix=f"fill_{index}",
        )
        look["label"] = f"Fill {chr(65 + index)}"
        look["bars"] = fill_bar_base
        fill_looks.append(look)

    release_look = _laser_look(
        track_seed=track_seed,
        base_pattern=release_pattern,
        context=context,
        kind=kind,
        ordinal=ordinal,
        token_suffix="release",
    )
    release_look["label"] = "Release Hook"
    release_look["bars"] = max(1, int(phrase_template["release_bars"]))

    return {
        "version": _LASER_PROGRAM_VERSION,
        "phrase_role": context,
        "zone_policy": _apply_venue_laser_zone_policy(venue_mode, _laser_zone_policy(kind, context)),
        "fill_trigger_every_bars": fill_cadence,
        "launch": launch_look,
        "sustain": sustain_looks,
        "fills": fill_looks,
        "release": release_look,
    }
