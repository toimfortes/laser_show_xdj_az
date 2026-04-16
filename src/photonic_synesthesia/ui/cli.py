"""
Command-Line Interface for Photonic Synesthesia.

Provides commands for running the system, testing fixtures,
and calibrating sensors.
"""

from __future__ import annotations

import logging
import signal
import socket
import sys
import time
from hashlib import sha1
from pathlib import Path
from typing import Any

import click
from click.core import ParameterSource

from photonic_synesthesia import __version__
from photonic_synesthesia.core.logging import configure_logging, get_logger

logger = get_logger(__name__)

_DEFAULT_REKORDBOX_XML_CANDIDATES = [
    Path.home() / "Documents" / "DJ" / "dj-agent" / "rekordbox.xml",
    Path.home() / "Documents" / "rekordbox.xml",
]

_LASER_PATTERN_POOLS: dict[str, list[str]] = {
    "intro": ["fan", "thin_scan", "wave", "liquid_sky"],
    "build": ["vertical_rake", "cone", "wave", "rotor", "liquid_sky"],
    "drop": ["burst_fan", "tunnel", "crisscross", "starburst", "shutter_hits", "alternating_beam_groups"],
    "breakdown": ["thin_scan", "liquid_sky", "fan", "wave", "cone"],
    "outro": ["fan", "thin_scan", "wave", "liquid_sky"],
}
_MOVER_PATTERN_POOLS: dict[str, list[str]] = {
    "intro": ["drift", "circle", "figure_eight", "leaf", "hold"],
    "build": ["rise", "circle", "figure_eight", "mirror_fan", "line_bounce"],
    "drop": ["cross_sweep", "snap_hits", "ping_pong_tilt", "square", "diamond", "mirror_fan"],
    "breakdown": ["hold", "drift", "leaf", "circle"],
    "outro": ["drift", "hold", "line_bounce"],
}
_WASH_PATTERN_POOLS: dict[str, list[str]] = {
    "intro": ["ambient", "breath", "gradient_roll", "center_out"],
    "build": ["bloom", "build_ramp", "center_out", "outside_in", "gradient_roll"],
    "drop": ["punch", "downbeat_hit", "white_peak", "drop_slam"],
    "breakdown": ["ambient", "breakdown_glow", "fade", "breath"],
    "outro": ["fade", "ambient", "breath"],
}
_LED_PATTERN_POOLS: dict[str, list[str]] = {
    "intro": ["pulse", "sparkle", "horizontal_lines", "fade", "horizontal_ramp"],
    "build": ["ramp", "vertical_build", "vertical_offset", "snake", "rotating_line"],
    "drop": ["chase", "rotating_line", "audio_spectrum", "fizzle", "snake"],
    "breakdown": ["sparkle", "pulse", "fade"],
    "outro": ["fade", "horizontal_ramp", "pulse"],
}

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
                "build": ["vertical_rake", "rotor", "cone", "wave", "liquid_sky"],
                "drop": ["shutter_hits", "burst_fan", "starburst", "alternating_beam_groups", "tunnel", "crisscross"],
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
                "intro": ["fan", "liquid_sky", "wave"],
                "build": ["cone", "wave", "vertical_rake", "rotor"],
                "drop": ["burst_fan", "tunnel", "starburst", "crisscross"],
                "breakdown": ["liquid_sky", "thin_scan", "fan"],
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
                "build": ["vertical_rake", "cone", "wave"],
                "drop": ["shutter_hits", "alternating_beam_groups", "burst_fan", "starburst"],
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
                "intro": ["wave", "liquid_sky", "fan"],
                "build": ["rotor", "cone", "wave", "vertical_rake"],
                "drop": ["tunnel", "crisscross", "rotor", "burst_fan"],
                "breakdown": ["liquid_sky", "wave", "thin_scan"],
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

_TRANSITION_PATTERN_HINTS: dict[str, dict[str, list[str]]] = {
    "build_riser": {
        "laser": ["vertical_rake", "rotor", "cone"],
        "mover": ["rise", "mirror_fan", "figure_eight"],
        "wash": ["build_ramp", "bloom", "outside_in"],
        "led": ["vertical_build", "ramp", "vertical_offset"],
    },
    "drop_launch": {
        "laser": ["shutter_hits", "burst_fan", "starburst", "alternating_beam_groups"],
        "mover": ["snap_hits", "cross_sweep", "ping_pong_tilt"],
        "wash": ["drop_slam", "white_peak", "downbeat_hit"],
        "led": ["chase", "fizzle", "audio_spectrum"],
    },
    "drop_variation": {
        "laser": ["tunnel", "crisscross", "burst_fan", "alternating_beam_groups"],
        "mover": ["square", "diamond", "cross_sweep", "ping_pong_tilt"],
        "wash": ["white_peak", "punch", "drop_slam"],
        "led": ["rotating_line", "snake", "audio_spectrum", "chase"],
    },
    "breakdown_release": {
        "laser": ["thin_scan", "liquid_sky", "fan"],
        "mover": ["hold", "leaf", "drift"],
        "wash": ["breakdown_glow", "fade", "ambient"],
        "led": ["sparkle", "fade", "pulse"],
    },
    "intro_set": {
        "laser": ["fan", "thin_scan", "wave"],
        "mover": ["drift", "circle", "leaf"],
        "wash": ["ambient", "breath", "center_out"],
        "led": ["pulse", "fade", "horizontal_lines"],
    },
    "outro_release": {
        "laser": ["fan", "thin_scan", "wave"],
        "mover": ["hold", "drift", "line_bounce"],
        "wash": ["fade", "ambient", "breath"],
        "led": ["fade", "horizontal_ramp", "pulse"],
    },
}

_CONTENT_FAMILY_BY_CONTEXT: dict[str, str] = {
    "intro_set": "beam",
    "build_riser": "transition",
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


def _discover_rekordbox_xml() -> Path | None:
    for candidate in _DEFAULT_REKORDBOX_XML_CANDIDATES:
        if candidate.is_file():
            return candidate
    return None


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _scene_for_marker_kind(kind: str) -> str:
    if kind == "drop":
        return "drop_intense"
    if kind == "build":
        return "break_sweep"
    if kind in {"breakdown", "bridge", "verse", "vocal"}:
        return "intro_ambient"
    if kind == "outro":
        return "intro_ambient"
    return "intro_ambient"


def _fixture_mode_for_marker_kind(kind: str) -> str:
    if kind == "drop":
        return "peak_return"
    if kind == "build":
        return "rebuild"
    if kind in {"breakdown", "bridge", "verse", "vocal"}:
        return "breakdown"
    if kind == "outro":
        return "outro"
    return "intro"


def _pattern_stage(kind: str) -> str:
    if kind == "drop":
        return "drop"
    if kind == "build":
        return "build"
    if kind in {"breakdown", "bridge", "verse", "vocal"}:
        return "breakdown"
    if kind == "outro":
        return "outro"
    return "intro"


def _stable_digest(label: str) -> bytes:
    return sha1(label.encode()).digest()


def _stable_float(label: str) -> float:
    return int.from_bytes(_stable_digest(label)[:8], "big") / float(2 ** 64)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


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
        return "build_riser" if previous_kind in {"breakdown", "bridge", "verse", "vocal"} else "intro_set"
    if stage == "breakdown":
        return "breakdown_release"
    if stage == "outro":
        return "outro_release"
    return "intro_set"


def _pattern_candidates(
    *,
    family: str,
    kind: str,
    context: str,
    profile: dict[str, Any],
) -> list[str]:
    stage = _pattern_stage(kind)
    pools = {
        "laser": _LASER_PATTERN_POOLS,
        "mover": _MOVER_PATTERN_POOLS,
        "wash": _WASH_PATTERN_POOLS,
        "led": _LED_PATTERN_POOLS,
    }
    base_candidates = list(pools[family].get(stage) or pools[family]["intro"])
    profile_candidates = list(profile.get("patterns", {}).get(family, {}).get(stage, []))
    transition_candidates = list(_TRANSITION_PATTERN_HINTS.get(context, {}).get(family, []))
    return _dedupe(transition_candidates + profile_candidates + base_candidates)


def _select_pattern(
    *,
    family: str,
    kind: str,
    context: str,
    profile: dict[str, Any],
    track_seed: str,
    marker_name: str,
    ordinal: int,
    previous_pattern: str | None,
) -> str:
    candidates = _pattern_candidates(family=family, kind=kind, context=context, profile=profile)
    if not candidates:
        raise RuntimeError(f"No pattern candidates for {family}:{kind}:{context}")
    if len(candidates) == 1:
        return candidates[0]
    digest = _stable_digest(f"{track_seed}:{family}:{kind}:{context}:{ordinal}:{marker_name}")
    start_index = int.from_bytes(digest[:2], "big") % len(candidates)
    ordered = candidates[start_index:] + candidates[:start_index]
    for candidate in ordered:
        if candidate != previous_pattern:
            return candidate
    return ordered[0]


def _section_levels(
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


def _fixture_enablement(
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


def _pick_word(track_seed: str, token: str, words: list[str]) -> str:
    index = int(_stable_float(f"{track_seed}:{token}") * len(words)) % len(words)
    return words[index]


def _variant_label(track_seed: str, token: str, base_pattern: str, adjectives: list[str], nouns: list[str]) -> str:
    adjective = _pick_word(track_seed, f"{token}:adj", adjectives)
    noun = _pick_word(track_seed, f"{token}:noun", nouns)
    base = base_pattern.replace("_", " ").title()
    return f"{adjective} {noun} {base}"


def _strobe_profile(
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


def _laser_variant(
    *,
    track_seed: str,
    base_pattern: str,
    kind: str,
    context: str,
    ordinal: int,
) -> dict[str, Any]:
    token = f"laser:{kind}:{context}:{ordinal}:{base_pattern}"
    return {
        "label": _variant_label(
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


def _laser_expression(
    *,
    track_seed: str,
    base_pattern: str,
    kind: str,
    context: str,
    ordinal: int,
) -> dict[str, Any]:
    token = f"laser-expression:{kind}:{context}:{ordinal}:{base_pattern}"
    geometry_family = {
        "burst_fan": "burst",
        "starburst": "burst",
        "alternating_beam_groups": "grouped",
        "shutter_hits": "grouped",
        "tunnel": "tunnel",
        "crisscross": "lattice",
        "vertical_rake": "rake",
        "liquid_sky": "sky",
        "cone": "cone",
        "thin_scan": "scan",
        "wave": "scan",
        "rotor": "helix",
    }.get(base_pattern, "fan")
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
        "label": _variant_label(
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


def _mover_variant(
    *,
    track_seed: str,
    base_pattern: str,
    kind: str,
    context: str,
    ordinal: int,
) -> dict[str, Any]:
    token = f"mover:{kind}:{context}:{ordinal}:{base_pattern}"
    return {
        "label": _variant_label(
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


def _wash_variant(
    *,
    track_seed: str,
    base_pattern: str,
    kind: str,
    context: str,
    ordinal: int,
) -> dict[str, Any]:
    token = f"wash:{kind}:{context}:{ordinal}:{base_pattern}"
    return {
        "label": _variant_label(
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


def _led_variant(
    *,
    track_seed: str,
    base_pattern: str,
    kind: str,
    context: str,
    ordinal: int,
) -> dict[str, Any]:
    token = f"led:{kind}:{context}:{ordinal}:{base_pattern}"
    return {
        "label": _variant_label(
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


def _default_show_sections(
    markers: list[dict[str, Any]],
    duration_seconds: float,
    *,
    track_seed: str | None = None,
) -> list[dict[str, Any]]:
    if not markers:
        seed = track_seed or "auto-groove"
        _, profile = _creative_profile(seed, [])
        intensity, motion, strobe = _section_levels(
            kind="drop",
            context="drop_launch",
            energy_scale=0.92,
            profile=profile,
            ordinal=0,
        )
        strobe_profile = _strobe_profile(
            kind="drop",
            context="drop_launch",
            track_seed=seed,
            ordinal=0,
            base_level=strobe,
        )
        laser_pattern = _select_pattern(
            family="laser",
            kind="drop",
            context="drop_launch",
            profile=profile,
            track_seed=seed,
            marker_name="Auto Groove",
            ordinal=0,
            previous_pattern=None,
        )
        mover_pattern = _select_pattern(
            family="mover",
            kind="drop",
            context="drop_launch",
            profile=profile,
            track_seed=seed,
            marker_name="Auto Groove",
            ordinal=0,
            previous_pattern=None,
        )
        wash_pattern = _select_pattern(
            family="wash",
            kind="drop",
            context="drop_launch",
            profile=profile,
            track_seed=seed,
            marker_name="Auto Groove",
            ordinal=0,
            previous_pattern=None,
        )
        led_pattern = _select_pattern(
            family="led",
            kind="drop",
            context="drop_launch",
            profile=profile,
            track_seed=seed,
            marker_name="Auto Groove",
            ordinal=0,
            previous_pattern=None,
        )
        return [
            {
                "id": "section_000",
                "label": "Auto Groove",
                "kind": "drop",
                "start_seconds": 0.0,
                "end_seconds": round(duration_seconds, 3),
                "scene_id": "drop_intense",
                "fixture_mode": "peak_return",
                "intensity_multiplier": intensity,
                "motion_multiplier": motion,
                "strobe_level": strobe,
                "strobe_profile": strobe_profile,
                "laser_pattern": laser_pattern,
                "laser_variant": _laser_variant(track_seed=seed, base_pattern=laser_pattern, kind="drop", context="drop_launch", ordinal=0),
                "laser_expression": _laser_expression(track_seed=seed, base_pattern=laser_pattern, kind="drop", context="drop_launch", ordinal=0),
                "mover_pattern": mover_pattern,
                "mover_variant": _mover_variant(track_seed=seed, base_pattern=mover_pattern, kind="drop", context="drop_launch", ordinal=0),
                "wash_pattern": wash_pattern,
                "wash_variant": _wash_variant(track_seed=seed, base_pattern=wash_pattern, kind="drop", context="drop_launch", ordinal=0),
                "led_pattern": led_pattern,
                "led_variant": _led_variant(track_seed=seed, base_pattern=led_pattern, kind="drop", context="drop_launch", ordinal=0),
                "laser_enabled": True,
                "movers_enabled": True,
                "washes_enabled": True,
                "leds_enabled": True,
            }
        ]

    seed = track_seed or "unknown-track"
    _, profile = _creative_profile(seed, markers)
    total_counts: dict[str, int] = {}
    for marker in markers:
        marker_kind = str(marker["kind"])
        total_counts[marker_kind] = total_counts.get(marker_kind, 0) + 1

    sections: list[dict[str, Any]] = []
    previous_patterns: dict[str, str | None] = {"laser": None, "mover": None, "wash": None, "led": None}
    kind_counts: dict[str, int] = {}
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
        context = _transition_context(
            previous_kind=previous_kind,
            kind=kind,
            next_kind=next_kind,
            ordinal=ordinal,
            total_of_kind=total_counts.get(kind, 1),
        )
        energy_hint = marker.get("energy_hint")
        energy_scale = max(0.25, min(1.0, float(energy_hint or 6) / 8.0))
        intensity_multiplier, motion_multiplier, strobe_level = _section_levels(
            kind=kind,
            context=context,
            energy_scale=energy_scale,
            profile=profile,
            ordinal=ordinal,
        )
        strobe_profile = _strobe_profile(
            kind=kind,
            context=context,
            track_seed=seed,
            ordinal=ordinal,
            base_level=strobe_level,
        )
        laser_pattern = _select_pattern(
            family="laser",
            kind=kind,
            context=context,
            profile=profile,
            track_seed=seed,
            marker_name=str(marker["name"]),
            ordinal=ordinal,
            previous_pattern=previous_patterns["laser"],
        )
        mover_pattern = _select_pattern(
            family="mover",
            kind=kind,
            context=context,
            profile=profile,
            track_seed=seed,
            marker_name=str(marker["name"]),
            ordinal=ordinal,
            previous_pattern=previous_patterns["mover"],
        )
        wash_pattern = _select_pattern(
            family="wash",
            kind=kind,
            context=context,
            profile=profile,
            track_seed=seed,
            marker_name=str(marker["name"]),
            ordinal=ordinal,
            previous_pattern=previous_patterns["wash"],
        )
        led_pattern = _select_pattern(
            family="led",
            kind=kind,
            context=context,
            profile=profile,
            track_seed=seed,
            marker_name=str(marker["name"]),
            ordinal=ordinal,
            previous_pattern=previous_patterns["led"],
        )
        previous_patterns.update({
            "laser": laser_pattern,
            "mover": mover_pattern,
            "wash": wash_pattern,
            "led": led_pattern,
        })
        laser_enabled, movers_enabled, washes_enabled, leds_enabled = _fixture_enablement(
            kind=kind,
            context=context,
            profile=profile,
            track_seed=seed,
            ordinal=ordinal,
        )
        laser_variant = _laser_variant(
            track_seed=seed,
            base_pattern=laser_pattern,
            kind=kind,
            context=context,
            ordinal=ordinal,
        )
        laser_expression = _laser_expression(
            track_seed=seed,
            base_pattern=laser_pattern,
            kind=kind,
            context=context,
            ordinal=ordinal,
        )
        mover_variant = _mover_variant(
            track_seed=seed,
            base_pattern=mover_pattern,
            kind=kind,
            context=context,
            ordinal=ordinal,
        )
        wash_variant = _wash_variant(
            track_seed=seed,
            base_pattern=wash_pattern,
            kind=kind,
            context=context,
            ordinal=ordinal,
        )
        led_variant = _led_variant(
            track_seed=seed,
            base_pattern=led_pattern,
            kind=kind,
            context=context,
            ordinal=ordinal,
        )
        sections.append(
            {
                "id": f"section_{index:03d}",
                "label": str(marker["name"]),
                "kind": kind,
                "start_seconds": round(float(marker["start_seconds"]), 3),
                "end_seconds": round(max(float(marker["start_seconds"]), next_start), 3),
                "scene_id": _scene_for_marker_kind(kind),
                "fixture_mode": _fixture_mode_for_marker_kind(kind),
                "intensity_multiplier": intensity_multiplier,
                "motion_multiplier": motion_multiplier,
                "strobe_level": strobe_level,
                "strobe_profile": strobe_profile,
                "laser_pattern": laser_pattern,
                "laser_variant": laser_variant,
                "laser_expression": laser_expression,
                "mover_pattern": mover_pattern,
                "mover_variant": mover_variant,
                "wash_pattern": wash_pattern,
                "wash_variant": wash_variant,
                "led_pattern": led_pattern,
                "led_variant": led_variant,
                "laser_enabled": laser_enabled,
                "movers_enabled": movers_enabled,
                "washes_enabled": washes_enabled,
                "leds_enabled": leds_enabled,
            }
        )
    return sections


def _validate_startup_config(settings: object, mock: bool = False) -> None:
    """
    Validate startup configuration before wiring runtime nodes.

    Fails fast on missing fixture profiles or obviously invalid address spans.
    """
    from photonic_synesthesia.core.config import Settings, load_fixture_profile
    from photonic_synesthesia.core.exceptions import ConfigError, FixtureProfileError, SceneError
    from photonic_synesthesia.laser import resolve_laser_profile

    if not isinstance(settings, Settings):
        raise ConfigError("Invalid settings object provided")

    # Mock mode permits running without fixture inventory.
    if not mock:
        enabled_fixtures = [fixture for fixture in settings.fixtures if fixture.enabled]
        if not enabled_fixtures:
            raise ConfigError("No enabled fixtures configured for live mode")

        for fixture in enabled_fixtures:
            profile_path = settings.fixtures_dir / f"{fixture.profile}.yaml"
            if not profile_path.exists():
                raise FixtureProfileError(fixture.profile, f"Profile not found at {profile_path}")

            profile = load_fixture_profile(profile_path)
            if fixture.type == "laser":
                resolved = resolve_laser_profile(fixture, settings.fixtures_dir)
                commissioning_required = bool(
                    resolved.safety.get("commissioning_required", False)
                    or resolved.adapter_assumption
                )
                if commissioning_required and not settings.runtime_flags.allow_unverified_laser_profiles:
                    raise FixtureProfileError(
                        fixture.profile,
                        (
                            f"Fixture '{fixture.id}' requires commissioning or verified mapping before live use. "
                            "Set PHOTONIC_RUNTIME_FLAGS__ALLOW_UNVERIFIED_LASER_PROFILES=true only for explicit override."
                        ),
                    )
                if resolved.control_surface == "ilda" and settings.ilda.enabled and settings.ilda.transport_type == "ether_dream":
                    try:
                        with socket.create_connection(
                            (settings.ilda.ether_dream_host, settings.ilda.ether_dream_port),
                            timeout=settings.ilda.ether_dream_timeout_s,
                        ):
                            pass
                    except OSError as exc:
                        raise ConfigError(
                            "Ether Dream DAC is not reachable for live ILDA output: "
                            f"{settings.ilda.ether_dream_host}:{settings.ilda.ether_dream_port} "
                            f"({exc})"
                        ) from exc
            channel_count = profile.get("channels")
            if isinstance(channel_count, int) and channel_count > 0:
                end_channel = fixture.start_address + channel_count - 1
                if end_channel > 512:
                    raise ConfigError(
                        f"Fixture '{fixture.id}' exceeds DMX universe: "
                        f"start={fixture.start_address}, channels={channel_count}, end={end_channel}"
                    )

    # Only require default scene file when a non-idle default is requested.
    default_scene = settings.scene.default_scene
    if default_scene != "idle":
        scenes_dir = settings.scene.scenes_dir
        has_default_scene = any(
            (scenes_dir / f"{default_scene}{ext}").exists()
            for ext in (".json", ".yaml", ".yml")
        )
        if not has_default_scene:
            raise SceneError(default_scene, f"Default scene file not found in {scenes_dir}")


@click.group()
@click.version_option(version=__version__)
@click.option("--debug", is_flag=True, help="Enable debug logging")
@click.option(
    "--config",
    type=click.Path(exists=True),
    help="Path to configuration file",
)
@click.pass_context
def cli(ctx: click.Context, debug: bool, config: str | None) -> None:
    """
    Photonic Synesthesia - AI-Driven Laser Show Controller for XDJ-AZ

    An autonomous lighting control system that uses LangGraph for orchestration,
    combining real-time audio analysis, MIDI telemetry, and computer vision
    to create structure-aware, music-reactive light shows.
    """
    ctx.ensure_object(dict)

    # Configure logging
    log_level = logging.DEBUG if debug else logging.INFO
    configure_logging(log_level)

    ctx.obj["debug"] = debug
    ctx.obj["config_path"] = Path(config) if config else None


@cli.command()
@click.option("--mock", is_flag=True, help="Use mock sensors (no hardware)")
@click.option("--fps", default=50.0, help="Target frames per second")
@click.pass_context
def run(ctx: click.Context, mock: bool, fps: float) -> None:
    """Run the photonic synesthesia system."""
    from photonic_synesthesia.core.config import Settings
    from photonic_synesthesia.graph import build_photonic_graph
    from photonic_synesthesia.platform import (
        ControlPlaneStateService,
        clear_shared_control_plane_service,
        set_shared_control_plane_service,
    )

    click.echo(f"Photonic Synesthesia v{__version__}")
    click.echo("=" * 50)

    # Load config
    if ctx.obj["config_path"]:
        settings = Settings.from_yaml(ctx.obj["config_path"])
    else:
        settings = Settings()

    settings.debug = ctx.obj["debug"]
    _validate_startup_config(settings, mock=mock)

    click.echo(f"Mode: {'Mock' if mock else 'Live'}")
    click.echo(f"Target FPS: {fps}")
    click.echo()

    # Build and run graph
    graph = None
    control_plane_service = set_shared_control_plane_service(ControlPlaneStateService())

    def _shutdown(signum: int, frame: object) -> None:
        """Signal handler: ask the graph to stop cleanly."""
        if graph is not None:
            graph.stop()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        graph = build_photonic_graph(
            settings,
            mock_sensors=mock,
            control_plane_service=control_plane_service,
        )
        click.echo("Graph built successfully. Starting...")
        click.echo("Press Ctrl+C to stop.")
        click.echo()

        graph.run_loop(target_fps=fps)

    except (KeyboardInterrupt, SystemExit):
        click.echo("\nShutting down...")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        if ctx.obj["debug"]:
            raise
        sys.exit(1)
    finally:
        if graph is not None:
            graph.stop()  # idempotent: stop() is safe to call multiple times
        clear_shared_control_plane_service()


@cli.command("run-file")
@click.argument("audio_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--fps", default=50.0, help="Target graph frames per second")
@click.option("--realtime/--offline", default=True, help="Sleep between chunks to mimic playback")
@click.option("--speed", default=1.0, type=float, help="Playback speed multiplier in realtime mode")
@click.option(
    "--rekordbox-xml",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Optional Rekordbox XML export used to match the song and import structure markers",
)
@click.option(
    "--ilda-transport",
    type=click.Choice(["memory", "ild", "ether_dream"], case_sensitive=False),
    default="ild",
    show_default=True,
    help="ILDA output mode for file playback",
)
@click.option(
    "--ilda-export-path",
    "ilda_export_path_override",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Optional .ild export path when --ilda-transport=ild",
)
@click.option("--ether-dream-host", help="Ether Dream host override when --ilda-transport=ether_dream")
@click.option("--ether-dream-port", type=int, help="Ether Dream port override when --ilda-transport=ether_dream")
@click.option("--web", "web_mode", is_flag=True, help="Serve the control-plane website in the same process")
@click.option("--web-host", default="127.0.0.1", help="Embedded web server host")
@click.option("--web-port", default=8000, type=int, help="Embedded web server port")
@click.pass_context
def run_file(
    ctx: click.Context,
    audio_file: Path,
    fps: float,
    realtime: bool,
    speed: float,
    rekordbox_xml: Path | None,
    ilda_transport: str,
    ilda_export_path_override: Path | None,
    ether_dream_host: str | None,
    ether_dream_port: int | None,
    web_mode: bool,
    web_host: str,
    web_port: int,
) -> None:
    """Run the graph against an audio file such as MP3 or WAV."""
    from photonic_synesthesia.core.config import Settings
    from photonic_synesthesia.graph import build_photonic_graph
    from photonic_synesthesia.graph.nodes.audio_file_sense import AudioFileSenseNode
    from photonic_synesthesia.integrations import load_rekordbox_track
    from photonic_synesthesia.integrations.show_plans import (
        ilda_export_path,
        load_show_plan,
        save_show_plan,
    )
    from photonic_synesthesia.platform import (
        ControlPlaneStateService,
        PlaybackContext,
        clear_shared_control_plane_service,
        clear_shared_playback_context,
        set_shared_control_plane_service,
        set_shared_playback_context,
    )
    from photonic_synesthesia.ui.web_panel import serve_in_thread

    if fps <= 0:
        click.echo("Error: --fps must be greater than 0", err=True)
        sys.exit(1)
    if speed <= 0:
        click.echo("Error: --speed must be greater than 0", err=True)
        sys.exit(1)
    if ether_dream_port is not None and not 1 <= ether_dream_port <= 65535:
        click.echo("Error: --ether-dream-port must be between 1 and 65535", err=True)
        sys.exit(1)
    if not 1 <= web_port <= 65535:
        click.echo("Error: --web-port must be between 1 and 65535", err=True)
        sys.exit(1)

    click.echo(f"Photonic Synesthesia v{__version__}")
    click.echo("=" * 50)

    if ctx.obj["config_path"]:
        settings = Settings.from_yaml(ctx.obj["config_path"])
    else:
        settings = Settings()

    settings.debug = ctx.obj["debug"]
    settings.ilda.enabled = True
    settings.ilda.transport_type = str(ilda_transport)
    settings.ilda.export_path = (
        ilda_export_path_override
        if ilda_export_path_override is not None
        else (ilda_export_path(audio_file.stem) if settings.ilda.transport_type == "ild" else None)
    )
    if ether_dream_host is not None:
        settings.ilda.ether_dream_host = ether_dream_host
    if ether_dream_port is not None:
        settings.ilda.ether_dream_port = ether_dream_port

    transport_source = ctx.get_parameter_source("ilda_transport")
    export_path_source = ctx.get_parameter_source("ilda_export_path_override")

    from photonic_synesthesia.laser import build_laser_profiles

    laser_profiles = build_laser_profiles(settings.fixtures, settings.fixtures_dir)
    enabled_fixture_ids = {fixture.id for fixture in settings.fixtures if fixture.enabled}
    enabled_ilda_fixture_ids = [
        fixture_id
        for fixture_id, profile in laser_profiles.items()
        if profile.control_surface == "ilda" and fixture_id in enabled_fixture_ids
    ]
    if not enabled_ilda_fixture_ids:
        explicit_ilda_request = (
            settings.ilda.transport_type == "ether_dream"
            or transport_source != ParameterSource.DEFAULT
            or export_path_source != ParameterSource.DEFAULT
        )
        if explicit_ilda_request:
            click.echo(
                "Error: ILDA output requested but no enabled ILDA-primary laser fixtures are configured.",
                err=True,
            )
            sys.exit(1)
        if settings.ilda.transport_type == "ild":
            click.echo("No ILDA fixtures configured; falling back to in-memory preview.")
            settings.ilda.transport_type = "memory"
            settings.ilda.export_path = None

    _validate_startup_config(settings, mock=settings.ilda.transport_type != "ether_dream")

    chunk_size = max(1, int(settings.audio.sample_rate / fps))
    audio_node = AudioFileSenseNode(
        audio_file,
        sample_rate=settings.audio.sample_rate,
        chunk_size=chunk_size,
        buffer_seconds=settings.audio.buffer_seconds,
    )

    click.echo(f"Mode: File Playback ({'realtime' if realtime else 'offline'})")
    click.echo(f"Audio File: {audio_file}")
    click.echo(f"Target FPS: {fps}")
    click.echo(f"Chunk Size: {chunk_size} samples")
    click.echo()

    matched_rekordbox_track = None
    rekordbox_source = rekordbox_xml or _discover_rekordbox_xml()
    if rekordbox_source is not None:
        matched_rekordbox_track = load_rekordbox_track(rekordbox_source, audio_file)
        if matched_rekordbox_track is not None:
            click.echo(
                "Rekordbox match: {artist} - {title} ({markers} markers)".format(
                    artist=matched_rekordbox_track.artist or "Unknown Artist",
                    title=matched_rekordbox_track.title,
                    markers=len(matched_rekordbox_track.markers),
                )
            )
            click.echo(f"Rekordbox XML: {rekordbox_source}")
            click.echo()

    track_key = (
        f"{matched_rekordbox_track.artist or ''}|{matched_rekordbox_track.title}"
        if matched_rekordbox_track
        else audio_file.stem
    )
    hardware_warnings: list[str] = []
    for fixture_id, profile in build_laser_profiles(settings.fixtures, settings.fixtures_dir).items():
        if profile.adapter_assumption:
            hardware_warnings.append(
                f"Laser '{fixture_id}' is using inferred adapter data. "
                "Keep ILDA primary and overhead-only until the real mapping is commissioned."
            )
    persisted_show_plan = load_show_plan(track_key)
    active_show_sections = (
        list(persisted_show_plan.get("show_sections", []))
        if persisted_show_plan and isinstance(persisted_show_plan.get("show_sections"), list)
        else _default_show_sections(
            [
                {
                    "name": marker.name,
                    "kind": marker.kind,
                    "start_seconds": round(marker.start_seconds, 3),
                    "energy_hint": marker.energy_hint,
                }
                for marker in (matched_rekordbox_track.markers if matched_rekordbox_track else [])
            ],
            audio_node.duration_seconds if web_mode else 0.0,
            track_seed=track_key,
        )
    )
    if (
        settings.ilda.transport_type == "ild"
        and ilda_export_path_override is None
    ):
        settings.ilda.export_path = ilda_export_path(track_key)

    if settings.ilda.transport_type == "ether_dream":
        click.echo(
            "ILDA Transport: Ether Dream "
            f"{settings.ilda.ether_dream_host}:{settings.ilda.ether_dream_port}"
        )
    elif settings.ilda.transport_type == "ild":
        click.echo(f"ILDA Transport: .ild export -> {settings.ilda.export_path}")
    else:
        click.echo("ILDA Transport: in-memory preview only")
    click.echo()

    graph = None
    web_server = None
    web_thread = None
    playback_context: PlaybackContext | None = None
    control_plane_service = set_shared_control_plane_service(ControlPlaneStateService())

    def _shutdown(signum: int, frame: object) -> None:
        if graph is not None:
            graph.stop()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        if web_mode:
            audio_node.start()
            playback_context = set_shared_playback_context(
                PlaybackContext(
                    file_path=str(audio_file),
                    file_name=audio_file.name,
                    duration_seconds=audio_node.duration_seconds,
                    track_title=matched_rekordbox_track.title if matched_rekordbox_track else audio_file.stem,
                    track_artist=matched_rekordbox_track.artist if matched_rekordbox_track else "",
                    track_key=track_key,
                    waveform=audio_node.waveform_preview(),
                    structure_markers=[
                        {
                            "name": marker.name,
                            "kind": marker.kind,
                            "start_seconds": round(marker.start_seconds, 3),
                            "energy_hint": marker.energy_hint,
                        }
                        for marker in (matched_rekordbox_track.markers if matched_rekordbox_track else [])
                    ],
                    show_sections=active_show_sections,
                    show_plan_path=str(
                        persisted_show_plan.get("saved_path", "")
                        if persisted_show_plan and persisted_show_plan.get("saved_path")
                        else ""
                    ),
                    ilda_transport_type=settings.ilda.transport_type,
                    ilda_export_path=str(settings.ilda.export_path or ""),
                    hardware_warnings=hardware_warnings,
                    _seek_callback=audio_node.seek,
                    _save_callback=lambda payload: str(save_show_plan(track_key, payload)),
                )
            )
            playback_context.persist_current_show_plan()
            playback_context.update_transport(
                playhead_seconds=0.0,
                playing=False,
                finished=False,
                realtime=realtime,
                speed=speed,
            )
            web_server, web_thread = serve_in_thread(
                services=control_plane_service,
                host=web_host,
                port=web_port,
            )
            click.echo(f"Web UI: http://{web_host}:{web_port}/")

        graph = build_photonic_graph(
            settings,
            mock_sensors=True,
            control_plane_service=control_plane_service,
            node_overrides={"audio_sense": audio_node},
        )
        graph.start()
        if web_mode and playback_context is not None:
            playback_context.update_transport(
                playhead_seconds=audio_node.playhead_seconds,
                playing=True,
                finished=audio_node.finished,
                realtime=realtime,
                speed=speed,
            )
        click.echo("Graph built successfully. Starting file playback...")
        click.echo("Press Ctrl+C to stop.")
        click.echo()

        last_reported_second = -1
        sleep_time = (1.0 / fps) / speed
        while graph._running and not audio_node.finished:  # noqa: SLF001 - controlled CLI loop
            frame_start = time.perf_counter()
            state = graph.step()
            if web_mode and playback_context is not None:
                playback_context.update_transport(
                    playhead_seconds=audio_node.playhead_seconds,
                    playing=not audio_node.finished,
                    finished=audio_node.finished,
                    realtime=realtime,
                    speed=speed,
                )

            playhead = int(audio_node.playhead_seconds)
            if playhead != last_reported_second:
                last_reported_second = playhead
                click.echo(
                    "t={playhead:5.1f}s / {duration:5.1f}s | scene={scene} | bpm={bpm:.1f}".format(
                        playhead=audio_node.playhead_seconds,
                        duration=audio_node.duration_seconds,
                        scene=state["scene_state"]["current_scene"],
                        bpm=state["beat_info"]["bpm"],
                    )
                )

            if realtime:
                elapsed = time.perf_counter() - frame_start
                remaining = sleep_time - elapsed
                if remaining > 0:
                    time.sleep(remaining)

        click.echo()
        click.echo("File playback complete.")

    except (KeyboardInterrupt, SystemExit):
        click.echo("\nShutting down...")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        if ctx.obj["debug"]:
            raise
        sys.exit(1)
    finally:
        if web_mode and playback_context is not None:
            playback_context.update_transport(
                playhead_seconds=audio_node.playhead_seconds,
                playing=False,
                finished=audio_node.finished,
                realtime=realtime,
                speed=speed,
            )
        if graph is not None:
            graph.stop()
        if web_server is not None:
            web_server.should_exit = True
        if web_thread is not None:
            web_thread.join(timeout=3.0)
        clear_shared_control_plane_service()
        clear_shared_playback_context()


@cli.command()
@click.option("--channel", "-c", type=int, required=True, help="DMX channel (1-512)")
@click.option("--value", "-v", type=int, required=True, help="Value (0-255)")
@click.pass_context
def dmx_test(ctx: click.Context, channel: int, value: int) -> None:
    """Test DMX output by setting a single channel."""
    from photonic_synesthesia.core.config import Settings
    from photonic_synesthesia.dmx.universe import is_valid_dmx_channel
    from photonic_synesthesia.graph.nodes.dmx_output import DMXOutputNode

    if not is_valid_dmx_channel(channel):
        click.echo("Error: Channel must be 1-512", err=True)
        sys.exit(1)

    if not 0 <= value <= 255:
        click.echo("Error: Value must be 0-255", err=True)
        sys.exit(1)

    settings = Settings()
    dmx = DMXOutputNode(settings.dmx)

    click.echo(f"Setting channel {channel} to {value}...")

    try:
        dmx.start()
        dmx.set_channel(channel, value)
        click.echo("Press Ctrl+C to stop and blackout.")

        import time

        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        click.echo("\nBlacking out...")
    finally:
        dmx.blackout()
        dmx.stop()


@cli.command()
@click.pass_context
def list_audio(ctx: click.Context) -> None:
    """List available audio input devices."""
    try:
        import sounddevice as sd

        devices = sd.query_devices()

        click.echo("Available audio devices:")
        click.echo("-" * 60)

        for i, device in enumerate(devices):
            if device["max_input_channels"] > 0:
                marker = " *" if i == sd.default.device[0] else "  "
                click.echo(f"{marker} [{i}] {device['name']}")
                click.echo(f"      Channels: {device['max_input_channels']}")
                click.echo(f"      Sample Rate: {device['default_samplerate']}")

    except ImportError:
        click.echo("Error: sounddevice not installed", err=True)
        sys.exit(1)


@cli.command()
@click.pass_context
def list_midi(ctx: click.Context) -> None:
    """List available MIDI input ports."""
    try:
        import mido

        ports = mido.get_input_names()

        click.echo("Available MIDI input ports:")
        click.echo("-" * 60)

        for port in ports:
            click.echo(f"  {port}")

        if not ports:
            click.echo("  (no MIDI ports found)")

    except ImportError:
        click.echo("Error: mido not installed", err=True)
        sys.exit(1)


@cli.command()
@click.option("--duration", "-d", default=10.0, help="Analysis duration in seconds")
@click.pass_context
def analyze(ctx: click.Context, duration: float) -> None:
    """Run audio analysis and display detected features."""
    import time

    from photonic_synesthesia.core.config import Settings
    from photonic_synesthesia.core.state import create_initial_state
    from photonic_synesthesia.graph.nodes.audio_sense import AudioSenseNode
    from photonic_synesthesia.graph.nodes.beat_track import BeatTrackNode
    from photonic_synesthesia.graph.nodes.feature_extract import FeatureExtractNode
    from photonic_synesthesia.graph.nodes.structure_detect import StructureDetectNode

    settings = Settings()
    state = create_initial_state()

    # Initialize nodes
    audio = AudioSenseNode(settings.audio)
    features = FeatureExtractNode()
    beats = BeatTrackNode(settings.beat_tracking)
    structure = StructureDetectNode(settings.structure_detection)

    click.echo(f"Analyzing audio for {duration} seconds...")
    click.echo("Press Ctrl+C to stop early.")
    click.echo()

    try:
        audio.start()
        start_time = time.time()

        while time.time() - start_time < duration:
            # Run analysis pipeline
            state = audio(state)
            state = features(state)
            state = beats(state)
            state = structure(state)

            # Display results
            af = state["audio_features"]
            bi = state["beat_info"]

            click.echo(
                f"\rBPM: {bi['bpm']:6.1f} | "
                f"Energy: {af['rms_energy']:5.3f} | "
                f"Structure: {state['current_structure'].value:12s} | "
                f"Drop Prob: {state['drop_probability']:4.2f}",
                nl=False,
            )

            time.sleep(0.05)

    except KeyboardInterrupt:
        pass
    finally:
        audio.stop()
        click.echo()


def main() -> None:
    """Entry point for the CLI."""
    cli(obj={})


if __name__ == "__main__":
    main()
