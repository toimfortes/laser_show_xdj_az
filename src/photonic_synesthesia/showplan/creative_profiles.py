"""Canonical creative-profile heuristic tables for the showplan facade.

These profiles steer pattern selection (laser / mover / wash / led) per
section kind (intro / build / drop / breakdown) and apply biases to the
strobe / motion / intensity channels. Previously duplicated verbatim in
``ui/cli.py`` and ``showplan/model_payloads.py`` with a "tests will
catch it" disclaimer — now owned here and imported by both.

Public names: ``CREATIVE_PROFILES`` (dict keyed by profile slug). Keep
the profile slugs stable; they appear in catalog payloads and recent-
catalog comparisons.
"""

from __future__ import annotations

from typing import Any

CREATIVE_PROFILES: dict[str, dict[str, Any]] = {
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
