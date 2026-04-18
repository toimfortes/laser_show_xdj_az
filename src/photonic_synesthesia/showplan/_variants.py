"""Pure deterministic variant / level / strobe / marker builders.

Internal leaf module. No imports from :mod:`photonic_synesthesia.ui` or
:mod:`photonic_synesthesia.platform.runtime_context`.
"""

from __future__ import annotations

from typing import Any

from photonic_synesthesia.showplan._patterns import (
    LASER_PATTERN_GEOMETRY as _LASER_PATTERN_GEOMETRY,
    _stable_float,
)
from photonic_synesthesia.showplan.types import clamp as _clamp, pattern_stage as _pattern_stage


_CONTENT_FAMILY_BY_CONTEXT: dict[str, str] = {
    "intro_set": "beam",
    "build_riser": "transition",
    "build_cycle": "transition",
    "drop_launch": "transition",
    "drop_variation": "beam",
    "breakdown_release": "abstract",
    "outro_release": "beam",
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


def pick_word(track_seed: str, token: str, words: list[str]) -> str:
    index = int(_stable_float(f"{track_seed}:{token}") * len(words)) % len(words)
    return words[index]


def variant_label(
    track_seed: str,
    token: str,
    base_pattern: str,
    adjectives: list[str],
    nouns: list[str],
) -> str:
    adjective = pick_word(track_seed, f"{token}:adj", adjectives)
    noun = pick_word(track_seed, f"{token}:noun", nouns)
    base = base_pattern.replace("_", " ").title()
    return f"{adjective} {noun} {base}"


def section_levels(
    *,
    kind: str,
    context: str,
    energy_scale: float,
    profile: dict[str, Any],
    ordinal: int,
) -> tuple[float, float, float]:
    stage = _pattern_stage(kind)
    base_intensity = {
        "intro": 0.44,
        "build": 0.66,
        "drop": 0.98,
        "breakdown": 0.36,
        "outro": 0.3,
    }[stage]
    base_motion = {
        "intro": 0.64,
        "build": 1.04,
        "drop": 1.28,
        "breakdown": 0.42,
        "outro": 0.48,
    }[stage]
    base_strobe = {
        "intro": 0.0,
        "build": 0.06,
        "drop": 0.28,
        "breakdown": 0.0,
        "outro": 0.0,
    }[stage]

    if context == "build_riser":
        base_motion += 0.1
        base_strobe += 0.04
    elif context == "drop_launch":
        base_intensity += 0.06
        base_motion += 0.12
        base_strobe += 0.18
    elif context == "drop_variation":
        base_intensity += 0.02
        base_motion += 0.08
        base_strobe += 0.1
    elif context == "breakdown_release":
        base_intensity -= 0.04
        base_motion -= 0.06

    profile_intensity = float(profile.get("intensity_bias", 0.0))
    profile_motion = float(profile.get("motion_bias", 0.0))
    profile_strobe = float(profile.get("strobe_bias", 0.0)) * {
        "intro": 0.08,
        "build": 0.45,
        "drop": 1.0,
        "breakdown": 0.1,
        "outro": 0.05,
    }[stage]
    ordinal_shift = min(0.12, ordinal * 0.04)
    intensity = _clamp(base_intensity + profile_intensity + (energy_scale - 0.6) * 0.35 + ordinal_shift * 0.2, 0.18, 1.28)
    motion = _clamp(base_motion + profile_motion + (energy_scale - 0.6) * 0.4 + ordinal_shift, 0.22, 2.2)
    strobe = _clamp(base_strobe + profile_strobe + (energy_scale - 0.6) * 0.18, 0.0, 1.0)
    return round(intensity, 3), round(motion, 3), round(strobe, 3)


def fixture_enablement(
    *,
    kind: str,
    context: str,
    profile: dict[str, Any],
    track_seed: str,
    ordinal: int,
) -> tuple[bool, bool, bool, bool]:
    stage = _pattern_stage(kind)
    lasers = True
    movers = True
    washes = True
    leds = True

    if stage == "intro":
        lasers = bool(profile.get("allow_intro_lasers", False))
        leds = bool(profile.get("allow_intro_leds", False))
    elif stage == "breakdown":
        lasers = bool(profile.get("allow_breakdown_lasers", False))
        leds = _stable_float(f"{track_seed}:breakdown_leds:{ordinal}") > 0.25
    elif stage == "outro":
        lasers = False
        movers = _stable_float(f"{track_seed}:outro_movers:{ordinal}") > 0.15
        leds = _stable_float(f"{track_seed}:outro_leds:{ordinal}") > 0.45

    if context == "drop_launch":
        lasers = True
        movers = True
        washes = True
        leds = True

    return lasers, movers, washes, leds


def strobe_profile(
    *,
    kind: str,
    context: str,
    track_seed: str,
    ordinal: int,
    base_level: float,
) -> dict[str, Any]:
    stage = _pattern_stage(kind)
    if stage in {"intro", "breakdown", "outro"}:
        mode = "restraint"
    elif context == "build_riser":
        mode = "riser"
    elif context == "drop_launch":
        mode = "impact"
    elif context == "drop_variation":
        mode = "burst"
    else:
        mode = "pulse"

    floor = 0.0 if stage != "drop" else base_level * 0.28
    ceiling = base_level
    if mode == "riser":
        floor = base_level * 0.12
        ceiling = _clamp(base_level + 0.12, 0.0, 1.0)
    elif mode == "impact":
        floor = base_level * 0.24
        ceiling = _clamp(base_level + 0.2, 0.0, 1.0)
    elif mode == "burst":
        floor = base_level * 0.18
        ceiling = _clamp(base_level + 0.08, 0.0, 1.0)
    elif mode == "restraint":
        floor = 0.0
        ceiling = min(base_level, 0.08 if stage == "breakdown" else 0.03)

    return {
        "mode": mode,
        "floor": round(floor, 3),
        "ceiling": round(ceiling, 3),
        "rate_multiplier": round(0.8 + _stable_float(f"{track_seed}:strobe_rate:{kind}:{ordinal}") * 1.8, 3),
        "shape": ["swell", "pulse", "gated", "burst"][int(_stable_float(f"{track_seed}:strobe_shape:{kind}:{ordinal}") * 4) % 4],
        "label": {
            "restraint": "restrained accents",
            "riser": "riser escalation",
            "impact": "impact hits",
            "burst": "burst accents",
            "pulse": "pulse accents",
        }[mode],
    }


def laser_variant(
    *,
    track_seed: str,
    base_pattern: str,
    kind: str,
    context: str,
    ordinal: int,
) -> dict[str, Any]:
    token = f"laser:{kind}:{context}:{ordinal}:{base_pattern}"
    return {
        "label": variant_label(
            track_seed,
            token,
            base_pattern,
            ["Helix", "Voltage", "Prism", "Skyline", "Vector", "Nova"],
            ["Fan", "Spray", "Arc", "Rake", "Matrix", "Tunnel"],
        ),
        "sweep_rate": round(0.75 + _stable_float(f"{token}:sweep") * 1.6, 3),
        "spread_scale": round(0.75 + _stable_float(f"{token}:spread") * 0.9, 3),
        "vertical_bias": round(0.55 + _stable_float(f"{token}:vertical") * 1.5, 3),
        "rotation_bias": round(0.55 + _stable_float(f"{token}:rotation") * 1.8, 3),
        "beam_density": round(0.75 + _stable_float(f"{token}:density") * 1.25, 3),
        "gate_sharpness": round(0.65 + _stable_float(f"{token}:gate") * 1.2, 3),
    }


def laser_expression(
    *,
    track_seed: str,
    base_pattern: str,
    kind: str,
    context: str,
    ordinal: int,
) -> dict[str, Any]:
    token = f"laser-expression:{kind}:{context}:{ordinal}:{base_pattern}"
    geometry_family = _LASER_PATTERN_GEOMETRY.get(base_pattern, "fan")
    stage = _pattern_stage(kind)
    color_mode = ["static", "morph", "white_hits", "dual_cycle"][int(_stable_float(f"{token}:color_mode") * 4) % 4]
    target_bias = ["crowd", "mid_air", "ceiling"][int(_stable_float(f"{token}:target") * 3) % 3]
    strategy = _GEOMETRY_STRATEGIES.get(geometry_family, _GEOMETRY_STRATEGIES["fan"])
    phrase_template = _PHRASE_ENVELOPES[stage]
    content_family = strategy["content_family"]
    if context in _CONTENT_FAMILY_BY_CONTEXT:
        content_family = _CONTENT_FAMILY_BY_CONTEXT[context]
    launch_intensity = 0.0
    sustain_intensity = 0.0
    release_intensity = 0.0
    sustain_motion = 0.0
    if stage == "drop":
        launch_intensity = round(0.94 + _stable_float(f"{token}:launch_intensity") * 0.2, 3)
        sustain_intensity = round(0.56 + _stable_float(f"{token}:sustain_intensity") * 0.22, 3)
        release_intensity = round(0.38 + _stable_float(f"{token}:release_intensity") * 0.18, 3)
        sustain_motion = round(0.76 + _stable_float(f"{token}:sustain_motion") * 0.35, 3)
    elif stage == "build":
        launch_intensity = round(0.44 + _stable_float(f"{token}:launch_intensity") * 0.18, 3)
        sustain_intensity = round(0.62 + _stable_float(f"{token}:sustain_intensity") * 0.18, 3)
        release_intensity = round(0.2 + _stable_float(f"{token}:release_intensity") * 0.16, 3)
        sustain_motion = round(0.88 + _stable_float(f"{token}:sustain_motion") * 0.42, 3)
    elif stage == "breakdown":
        launch_intensity = round(0.18 + _stable_float(f"{token}:launch_intensity") * 0.1, 3)
        sustain_intensity = round(0.28 + _stable_float(f"{token}:sustain_intensity") * 0.12, 3)
        release_intensity = round(0.16 + _stable_float(f"{token}:release_intensity") * 0.1, 3)
        sustain_motion = round(0.42 + _stable_float(f"{token}:sustain_motion") * 0.2, 3)
    else:
        launch_intensity = round(0.26 + _stable_float(f"{token}:launch_intensity") * 0.14, 3)
        sustain_intensity = round(0.34 + _stable_float(f"{token}:sustain_intensity") * 0.18, 3)
        release_intensity = round(0.22 + _stable_float(f"{token}:release_intensity") * 0.12, 3)
        sustain_motion = round(0.54 + _stable_float(f"{token}:sustain_motion") * 0.24, 3)

    variation_plan = {
        "intro": [
            "introduce beams sparsely",
            "favor aerial holds over crowd hits",
            "let colors drift slowly across phrases",
        ],
        "build": [
            "tighten geometry every phrase block",
            "increase vertical pressure into the riser",
            "save impact gating for the handoff",
        ],
        "drop": [
            "hit hard for the launch bars",
            "normalize to a groove after the launch",
            "rotate between chase, fan, and abstract looks mid-drop",
        ],
        "breakdown": [
            "reduce beam density and keep lasers overhead",
            "favor melodic abstracts and tunnels",
            "avoid sustained shuttering",
        ],
        "outro": [
            "strip away density",
            "return to simple fans and scans",
            "prepare a clean handoff for mix-out",
        ],
    }[stage]
    return {
        "label": variant_label(
            track_seed,
            token,
            base_pattern,
            ["Aerial", "Crowd", "Prism", "Helix", "Voltage", "Sky"],
            ["Engine", "Vector", "Drive", "Pulse", "Lattice", "Sweep"],
        ),
        "content_family": content_family,
        "geometry_family": geometry_family,
        "color_mode": color_mode,
        "target_bias": target_bias,
        "target_strategy": strategy["target_strategy"],
        "blanking_strategy": strategy["blanking_strategy"],
        "color_strategy": strategy["color_strategy"],
        "phrase_envelope": {
            **phrase_template,
            "launch_intensity": launch_intensity,
            "sustain_intensity": sustain_intensity,
            "release_intensity": release_intensity,
            "sustain_motion": sustain_motion,
        },
        "transition_role": context,
        "variation_plan": variation_plan,
        "x_amplitude": round(0.72 + _stable_float(f"{token}:x_amp") * 1.1, 3),
        "y_amplitude": round(0.45 + _stable_float(f"{token}:y_amp") * 1.5, 3),
        "rotation_rate": round(0.65 + _stable_float(f"{token}:rot_rate") * 1.8, 3),
        "sweep_density": round(0.75 + _stable_float(f"{token}:density") * 1.2, 3),
        "color_cycle_rate": round(0.2 + _stable_float(f"{token}:color_rate") * 1.8, 3),
        "white_accent": round(_stable_float(f"{token}:white_accent"), 3),
        "mirror": _stable_float(f"{token}:mirror") > 0.45,
        "crowd_bias": round(_stable_float(f"{token}:crowd_bias"), 3),
        "ceiling_bias": round(_stable_float(f"{token}:ceiling_bias"), 3),
    }


def mover_variant(
    *,
    track_seed: str,
    base_pattern: str,
    kind: str,
    context: str,
    ordinal: int,
) -> dict[str, Any]:
    token = f"mover:{kind}:{context}:{ordinal}:{base_pattern}"
    return {
        "label": variant_label(
            track_seed,
            token,
            base_pattern,
            ["Orbit", "Vector", "Mirror", "Pulse", "Ribbon", "Velocity"],
            ["Sweep", "Trace", "Drift", "Lattice", "Arc", "Figure"],
        ),
        "pan_scale": round(0.72 + _stable_float(f"{token}:pan") * 0.9, 3),
        "tilt_scale": round(0.72 + _stable_float(f"{token}:tilt") * 0.95, 3),
        "phase_scale": round(0.75 + _stable_float(f"{token}:phase") * 1.2, 3),
        "hit_bias": round(_stable_float(f"{token}:hit"), 3),
        "beam_scale": round(0.82 + _stable_float(f"{token}:beam") * 0.65, 3),
    }


def wash_variant(
    *,
    track_seed: str,
    base_pattern: str,
    kind: str,
    context: str,
    ordinal: int,
) -> dict[str, Any]:
    token = f"wash:{kind}:{context}:{ordinal}:{base_pattern}"
    return {
        "label": variant_label(
            track_seed,
            token,
            base_pattern,
            ["Halo", "Bloom", "Tidal", "Velvet", "Prism", "Lunar"],
            ["Glow", "Cloud", "Bloom", "Wash", "Swell", "Haze"],
        ),
        "radius_scale": round(0.8 + _stable_float(f"{token}:radius") * 0.8, 3),
        "pulse_depth": round(0.45 + _stable_float(f"{token}:pulse") * 0.9, 3),
        "fade_bias": round(_stable_float(f"{token}:fade"), 3),
    }


def led_variant(
    *,
    track_seed: str,
    base_pattern: str,
    kind: str,
    context: str,
    ordinal: int,
) -> dict[str, Any]:
    token = f"led:{kind}:{context}:{ordinal}:{base_pattern}"
    return {
        "label": variant_label(
            track_seed,
            token,
            base_pattern,
            ["Pixel", "Neon", "Spectrum", "Prism", "Voltage", "Signal"],
            ["Rush", "Grid", "Ribbon", "Shimmer", "Surge", "Flow"],
        ),
        "chase_rate": round(0.75 + _stable_float(f"{token}:chase") * 1.5, 3),
        "density": round(0.7 + _stable_float(f"{token}:density") * 1.2, 3),
        "glow_bias": round(0.5 + _stable_float(f"{token}:glow") * 0.9, 3),
    }


def auto_markers_for_duration(duration_seconds: float) -> list[dict[str, Any]]:
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
