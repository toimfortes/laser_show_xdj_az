"""
Command-Line Interface for Photonic Synesthesia.

Provides commands for running the system, testing fixtures,
and calibrating sensors.
"""

from __future__ import annotations

import copy
import json
import logging
import math
import os
import signal
import socket
import sys
import time
from hashlib import sha1
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

import click
from click.core import ParameterSource

from photonic_synesthesia import __version__
from photonic_synesthesia.core.logging import configure_logging, get_logger
from photonic_synesthesia.showplan import (
    build_catalog_model_payload as _build_catalog_model_payload,
)
from photonic_synesthesia.showplan import (
    build_cue_recipe as _cue_recipe,
)
from photonic_synesthesia.showplan import (
    build_laser_program as _laser_program,
)
from photonic_synesthesia.showplan import (
    build_show_catalog_entry as _showplan_build_show_catalog_entry,
)
from photonic_synesthesia.showplan import (
    resolve_show_sections as _showplan_resolve_show_sections,
)
from photonic_synesthesia.showplan._variants import (
    auto_markers_for_duration as _auto_markers_for_duration,
)
from photonic_synesthesia.showplan._variants import (
    fixture_enablement as _fixture_enablement,
)
from photonic_synesthesia.showplan._variants import (
    laser_expression as _laser_expression,
)
from photonic_synesthesia.showplan._variants import (
    laser_variant as _laser_variant,
)
from photonic_synesthesia.showplan._variants import (
    led_variant as _led_variant,
)
from photonic_synesthesia.showplan._variants import (
    mover_variant as _mover_variant,
)
from photonic_synesthesia.showplan._variants import (
    section_levels as _section_levels,
)
from photonic_synesthesia.showplan._variants import (
    strobe_profile as _strobe_profile,
)
from photonic_synesthesia.showplan._variants import (
    wash_variant as _wash_variant,
)
from photonic_synesthesia.showplan.sections import (
    fixture_role_map as _fixture_role_map,
)
from photonic_synesthesia.showplan.sections import (
    normalize_section_role as _normalize_section_role,
)
from photonic_synesthesia.showplan.sections import (
    transition_context as _transition_context,
)
from photonic_synesthesia.showplan.sections import (
    transition_intent as _transition_intent,
)
from photonic_synesthesia.showplan.selection import (
    select_section_patterns as _showplan_select_section_patterns,
)
from photonic_synesthesia.showplan.semantic_profile import (
    build_semantic_profile as _showplan_build_semantic_profile,
)
from photonic_synesthesia.showplan.semantic_profile import (
    metadata_confidence as _showplan_metadata_confidence,
)
from photonic_synesthesia.showplan.types import (
    CATALOG_VERSION as _CATALOG_VERSION,
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
    VENUE_MODES as _VENUE_MODES,
)
from photonic_synesthesia.showplan.types import (
    apply_venue_laser_zone_policy as _apply_venue_laser_zone_policy,
)
from photonic_synesthesia.showplan.types import (
    clamp as _clamp,
)
from photonic_synesthesia.showplan.types import (
    cue_family_id as _cue_family_id,
)
from photonic_synesthesia.showplan.types import (
    laser_zone_policy as _laser_zone_policy,
)
from photonic_synesthesia.showplan.types import (
    normalize_venue_mode as _normalize_venue_mode,
)
from photonic_synesthesia.showplan.types import (
    pattern_stage as _pattern_stage,
)
from photonic_synesthesia.showplan.validation import (
    anti_template_validation as _showplan_anti_template_validation,
)
from photonic_synesthesia.showplan.validation import (
    show_fingerprint as _show_fingerprint,
)

logger = get_logger(__name__)

_SELECTION_MODES = {"procedural", "ai_assisted", "local_ollama_cpu"}
_OLLAMA_CPU_MODEL = "qwen2.5:1.5b"
_OLLAMA_DEFAULT_HOST = "http://127.0.0.1:11434"
_OLLAMA_CPU_KEEP_ALIVE = "10m"
_OLLAMA_CPU_TIMEOUT_SECONDS = 6.0
_OLLAMA_CPU_MAX_CANDIDATES = 6
_CATALOG_AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".aiff", ".aif", ".m4a", ".ogg"}

_DEFAULT_REKORDBOX_XML_CANDIDATES = [
    Path.home() / "Documents" / "DJ" / "dj-agent" / "rekordbox.xml",
    Path.home() / "Documents" / "rekordbox.xml",
]

_LASER_PATTERN_POOLS: dict[str, list[str]] = {
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

_TRANSITION_PATTERN_HINTS: dict[str, dict[str, list[str]]] = {
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

_LASER_PATTERN_GEOMETRY: dict[str, str] = {
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


def _show_plan_payload_saver(default_track_key: str) -> Any:
    from photonic_synesthesia.integrations.show_plans import save_show_plan

    return lambda payload: str(save_show_plan(str(payload.get("track_key") or default_track_key), payload))


def _catalog_entry_as_show_plan(catalog_entry: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(catalog_entry, dict):
        return None
    if not isinstance(catalog_entry.get("show_sections"), list):
        return None
    return {
        "track_key": str(catalog_entry.get("track_key") or ""),
        "track_title": str(catalog_entry.get("track_title") or ""),
        "track_artist": str(catalog_entry.get("track_artist") or ""),
        "duration_seconds": catalog_entry.get("duration_seconds"),
        "semantic_profile": copy.deepcopy(catalog_entry.get("semantic_profile", {})),
        "metadata_confidence": copy.deepcopy(catalog_entry.get("metadata_confidence", {})),
        "motif_registry": copy.deepcopy(catalog_entry.get("motif_registry", {})),
        "show_fingerprint": copy.deepcopy(catalog_entry.get("show_fingerprint", {})),
        "anti_template_validation": copy.deepcopy(catalog_entry.get("anti_template_validation", {})),
        "scorer_bundle": copy.deepcopy(catalog_entry.get("scorer_bundle", {})),
        "preview_artifacts": copy.deepcopy(catalog_entry.get("preview_artifacts", {})),
        "venue_mode": _normalize_venue_mode(catalog_entry.get("venue_mode")),
        "structure_markers": [dict(marker) for marker in catalog_entry.get("structure_markers", [])],
        "show_sections": [dict(section) for section in catalog_entry.get("show_sections", [])],
        "selection_mode": catalog_entry.get("selection_mode"),
        "selection_variance": catalog_entry.get("selection_variance"),
        "saved_path": catalog_entry.get("saved_path") or catalog_entry.get("catalog_path") or "",
    }


def _load_precomputed_show_plan(track_key: str) -> tuple[dict[str, Any] | None, str]:
    from photonic_synesthesia.integrations.show_catalog import load_show_catalog
    from photonic_synesthesia.integrations.show_plans import load_show_plan

    persisted_show_plan = load_show_plan(track_key)
    if persisted_show_plan is not None:
        return persisted_show_plan, "show_plan"
    catalog_entry = load_show_catalog(track_key)
    catalog_show_plan = _catalog_entry_as_show_plan(catalog_entry)
    if catalog_show_plan is not None:
        return catalog_show_plan, "catalog"
    return None, "generated"


def _audio_file_duration_seconds(audio_file: Path) -> float:
    from photonic_synesthesia.graph.nodes.audio_file_sense import librosa

    if librosa is None:
        raise RuntimeError("librosa is required for catalog generation")
    try:
        return float(librosa.get_duration(path=str(audio_file)))
    except TypeError:
        return float(librosa.get_duration(filename=str(audio_file)))


def _ollama_model_name() -> str:
    return str(os.environ.get("PHOTONIC_OLLAMA_MODEL") or _OLLAMA_CPU_MODEL).strip() or _OLLAMA_CPU_MODEL


def _ollama_host() -> str:
    raw = (
        os.environ.get("PHOTONIC_OLLAMA_HOST")
        or os.environ.get("OLLAMA_HOST")
        or _OLLAMA_DEFAULT_HOST
    )
    host = str(raw).strip() or _OLLAMA_DEFAULT_HOST
    if "://" not in host:
        host = f"http://{host}"
    return host.rstrip("/")


def _ollama_generate_endpoint() -> str:
    host = _ollama_host()
    return host if host.endswith("/api/generate") else f"{host}/api/generate"


def _ollama_num_gpu_option() -> int | None:
    raw = os.environ.get("PHOTONIC_OLLAMA_NUM_GPU")
    if raw is None or str(raw).strip() == "":
        return 0
    try:
        value = int(str(raw).strip())
    except ValueError:
        return 0
    return None if value < 0 else value


def _discover_audio_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix.lower() in _CATALOG_AUDIO_EXTENSIONS else []
    return sorted(
        candidate
        for candidate in path.rglob("*")
        if candidate.is_file() and candidate.suffix.lower() in _CATALOG_AUDIO_EXTENSIONS
    )


def _fetch_catalog_web_enrichment(
    *,
    track_title: str,
    track_artist: str,
    duration_seconds: float,
) -> dict[str, Any]:
    from photonic_synesthesia.integrations import fetch_web_enrichment

    return fetch_web_enrichment(
        title=track_title,
        artist=track_artist,
        duration_seconds=duration_seconds,
    )


def _build_semantic_profile(
    *,
    track_title: str,
    track_artist: str,
    duration_seconds: float,
    structure_markers: list[dict[str, Any]],
    rekordbox_average_bpm: float | None = None,
    web_enrichment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _showplan_build_semantic_profile(
        track_title=track_title,
        track_artist=track_artist,
        duration_seconds=duration_seconds,
        structure_markers=structure_markers,
        rekordbox_average_bpm=rekordbox_average_bpm,
        web_enrichment=web_enrichment,
    )


def _metadata_confidence(
    *,
    structure_markers: list[dict[str, Any]],
    metadata_source: str,
    rekordbox_track_id: str = "",
    rekordbox_average_bpm: float | None = None,
    web_enrichment: dict[str, Any] | None = None,
    matched_rekordbox_track: bool = False,
) -> dict[str, Any]:
    return _showplan_metadata_confidence(
        structure_markers=structure_markers,
        metadata_source=metadata_source,
        rekordbox_track_id=rekordbox_track_id,
        rekordbox_average_bpm=rekordbox_average_bpm,
        web_enrichment=web_enrichment,
        matched_rekordbox_track=matched_rekordbox_track,
    )


def _section_motif_ids(section: dict[str, Any]) -> list[str]:
    section_role = str(section.get("section_role") or section.get("kind") or "section")
    lead_family = str(section.get("lead_family") or "none")
    motifs = [f"role:{section_role}", f"lead:{section_role}:{lead_family}"]
    for family in ("laser", "mover", "wash", "led"):
        enabled_flag = bool(section.get(f"{family if family != 'led' else 'led'}s_enabled", False))
        if family == "laser":
            enabled_flag = bool(section.get("laser_enabled", False))
        elif family == "mover":
            enabled_flag = bool(section.get("movers_enabled", False))
        elif family == "wash":
            enabled_flag = bool(section.get("washes_enabled", False))
        elif family == "led":
            enabled_flag = bool(section.get("leds_enabled", False))
        if not enabled_flag:
            continue
        pattern = str(section.get(f"{family}_pattern") or "")
        if pattern:
            motifs.append(f"{family}:{pattern}")
    geometry = str(section.get("laser_expression", {}).get("geometry_family") or "")
    if geometry:
        motifs.append(f"laser_geometry:{geometry}")
    transition_type = str(section.get("transition_intent", {}).get("type") or "")
    if transition_type:
        motifs.append(f"transition:{transition_type}")
    return motifs


def _decorate_show_sections_with_motifs(show_sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    motif_counts: dict[str, int] = {}
    for section in show_sections:
        motif_ids = _section_motif_ids(section)
        for motif_id in motif_ids:
            motif_counts[motif_id] = motif_counts.get(motif_id, 0) + 1
        section["motif_ids"] = motif_ids
        section["motif_primary"] = motif_ids[0] if motif_ids else ""
    for section in show_sections:
        cue_recipe = section.get("cue_recipe")
        if isinstance(cue_recipe, dict):
            cue_recipe["motif_ids"] = list(section.get("motif_ids") or [])
            cue_recipe["motif_primary"] = str(section.get("motif_primary") or "")
            cue_recipe["motif_reuse_count"] = max(
                (motif_counts.get(motif_id, 0) for motif_id in cue_recipe["motif_ids"]),
                default=0,
            )
    return show_sections


def _recent_catalog_entries(current_track_key: str, limit: int = 4) -> list[dict[str, Any]]:
    from photonic_synesthesia.integrations import list_show_catalog_paths

    entries: list[tuple[float, dict[str, Any]]] = []
    for path in list_show_catalog_paths():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(payload.get("track_key") or "") == current_track_key:
            continue
        try:
            modified = path.stat().st_mtime
        except OSError:
            modified = 0.0
        entries.append((modified, payload))
    entries.sort(key=lambda item: item[0], reverse=True)
    return [payload for _, payload in entries[: max(0, limit)]]


def _anti_template_validation(
    *,
    track_key: str,
    show_sections: list[dict[str, Any]],
    semantic_profile: dict[str, Any] | None,
    recent_catalog_entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    resolved_recent = list(recent_catalog_entries or _recent_catalog_entries(track_key))
    return _showplan_anti_template_validation(
        track_key=track_key,
        show_sections=show_sections,
        semantic_profile=semantic_profile,
        recent_catalog_entries=resolved_recent,
    )


def _motif_registry(
    *,
    track_key: str,
    show_sections: list[dict[str, Any]],
    recent_catalog_entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    recent_entries = list(recent_catalog_entries or _recent_catalog_entries(track_key))
    recent_track_keys = [str(payload.get("track_key") or "") for payload in recent_entries[:4]]
    current_motifs = sorted({motif for section in show_sections for motif in list(section.get("motif_ids") or [])})
    recent_motifs = sorted(
        {
            motif
            for payload in recent_entries[:4]
            for motif in list((payload.get("show_fingerprint") or {}).get("motif_ids") or [])
        }
    )
    return {
        "version": 1,
        "window": 4,
        "recent_track_keys": recent_track_keys,
        "current_motifs": current_motifs,
        "recent_motifs": recent_motifs,
        "reused_motifs": sorted(set(current_motifs) & set(recent_motifs)),
    }


def _scorer_bundle(
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
        len([family for family, payload in dict(section.get("fixture_role_map") or {}).items() if str(payload.get("role") or "") == "hero"]) == 1
        for section in show_sections
    )
    fixture_hierarchy = 1.0 if hero_lock_ok else 0.5
    intensity_values = [float(section.get("intensity_multiplier") or 0.0) for section in show_sections]
    motion_values = [float(section.get("motion_multiplier") or 0.0) for section in show_sections]
    strobe_values = [float(section.get("strobe_level") or 0.0) for section in show_sections]
    visual_contrast = round(
        _clamp((max(intensity_values, default=0.0) - min(intensity_values, default=0.0)) * 0.45
               + (max(motion_values, default=0.0) - min(motion_values, default=0.0)) * 0.35
               + (max(strobe_values, default=0.0) - min(strobe_values, default=0.0)) * 0.2, 0.0, 1.0),
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
    drop_sections = [section for section in show_sections if str(section.get("section_role") or "").startswith("drop")]
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
            + (0.08 if any(str(section.get("transition_intent", {}).get("type") or "") == "suckout" for section in show_sections) else 0.0),
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
            ) / max(1, len(show_sections)),
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


def _preview_artifacts(track_key: str, show_sections: list[dict[str, Any]]) -> dict[str, Any]:
    slug = sha1(track_key.encode("utf-8")).hexdigest()[:10]
    artifacts: list[dict[str, Any]] = []
    for section in show_sections:
        section_id = str(section.get("id") or "section")
        label = str(section.get("label") or section_id)
        artifacts.append(
            {
                "type": "section_still",
                "section_id": section_id,
                "label": label,
                "path_hint": f"previz/{slug}/{section_id}_still.png",
            }
        )
        artifacts.append(
            {
                "type": "section_clip",
                "section_id": section_id,
                "label": label,
                "path_hint": f"previz/{slug}/{section_id}_clip.mp4",
            }
        )
    for section in show_sections:
        section_role = str(section.get("section_role") or "")
        if section_role in {"build_2", "drop_1", "drop_variation", "breakdown"}:
            section_id = str(section.get("id") or "section")
            artifacts.append(
                {
                    "type": "long_exposure",
                    "section_id": section_id,
                    "label": str(section.get("label") or section_id),
                    "path_hint": f"previz/{slug}/{section_id}_long_exposure.png",
                }
            )
    return {
        "version": 1,
        "status": "planned",
        "summary": {
            "section_stills": sum(1 for artifact in artifacts if artifact["type"] == "section_still"),
            "section_clips": sum(1 for artifact in artifacts if artifact["type"] == "section_clip"),
            "long_exposures": sum(1 for artifact in artifacts if artifact["type"] == "long_exposure"),
        },
        "artifacts": artifacts,
    }


def _build_track_metadata_binding_callback(
    *,
    rekordbox_xml: Path | None,
    fallback_track_key: str,
    fallback_title: str,
    fallback_artist: str = "",
    fallback_duration_seconds: float = 0.0,
    fallback_venue_mode: str = "small_room_50_100",
) -> Any:
    from photonic_synesthesia.integrations import load_rekordbox_track_by_metadata

    def _bind(metadata: dict[str, Any]) -> dict[str, Any]:
        requested_title = str(metadata.get("track_title") or metadata.get("title") or fallback_title).strip()
        requested_artist = str(metadata.get("track_artist") or metadata.get("artist") or fallback_artist).strip()
        requested_duration = metadata.get("duration_seconds", fallback_duration_seconds)
        expected_bpm = metadata.get("expected_bpm")
        metadata_source = str(metadata.get("metadata_source") or "pro_dj_link")

        matched_rekordbox_track = (
            load_rekordbox_track_by_metadata(
                rekordbox_xml,
                title=requested_title,
                artist=requested_artist,
                duration_seconds=float(requested_duration or 0.0) or None,
                expected_bpm=float(expected_bpm) if expected_bpm is not None else None,
            )
            if rekordbox_xml is not None
            else None
        )

        structure_markers = [
            {
                "name": marker.name,
                "kind": marker.kind,
                "start_seconds": round(marker.start_seconds, 3),
                "energy_hint": marker.energy_hint,
            }
            for marker in (matched_rekordbox_track.markers if matched_rekordbox_track else [])
        ]
        track_title = matched_rekordbox_track.title if matched_rekordbox_track else requested_title or fallback_title
        track_artist = matched_rekordbox_track.artist if matched_rekordbox_track else requested_artist
        track_key = (
            f"{track_artist or ''}|{track_title}".strip("|")
            if track_title
            else fallback_track_key
        ) or fallback_track_key

        duration_seconds = (
            float(requested_duration or 0.0)
            or float(matched_rekordbox_track.total_time if matched_rekordbox_track else 0.0)
            or float(fallback_duration_seconds)
        )
        persisted_show_plan, show_source = _load_precomputed_show_plan(track_key)
        if not structure_markers and persisted_show_plan and isinstance(
            persisted_show_plan.get("structure_markers"), list
        ):
            structure_markers = [
                dict(marker) for marker in persisted_show_plan.get("structure_markers", [])
            ]
        selection_mode = _normalize_selection_mode(
            metadata.get("selection_mode")
            if metadata.get("selection_mode") is not None
            else (persisted_show_plan or {}).get("selection_mode")
        )
        selection_variance = _normalize_selection_variance(
            metadata.get("selection_variance")
            if metadata.get("selection_variance") is not None
            else (persisted_show_plan or {}).get("selection_variance")
        )
        venue_mode = _normalize_venue_mode(
            metadata.get("venue_mode")
            if metadata.get("venue_mode") is not None
            else (persisted_show_plan or {}).get("venue_mode", fallback_venue_mode)
        )
        semantic_profile = copy.deepcopy((persisted_show_plan or {}).get("semantic_profile", {}))
        metadata_confidence = copy.deepcopy(metadata.get("metadata_confidence", {}))
        if not metadata_confidence:
            metadata_confidence = copy.deepcopy((persisted_show_plan or {}).get("metadata_confidence", {}))
        if not metadata_confidence:
            metadata_confidence = _metadata_confidence(
                structure_markers=structure_markers,
                metadata_source=metadata_source,
                rekordbox_track_id=matched_rekordbox_track.track_id if matched_rekordbox_track else "",
                rekordbox_average_bpm=matched_rekordbox_track.average_bpm if matched_rekordbox_track else None,
                web_enrichment=None,
                matched_rekordbox_track=matched_rekordbox_track is not None,
            )
        show_sections = _resolve_show_sections(
            persisted_show_plan,
            structure_markers,
            duration_seconds,
            track_seed=track_key,
            semantic_profile=semantic_profile,
            selection_mode=selection_mode,
            selection_variance=selection_variance,
            venue_mode=venue_mode,
            metadata_confidence=metadata_confidence,
        )
        return {
            "track_title": track_title,
            "track_artist": track_artist,
            "track_key": track_key,
            "file_name": f"{track_artist} - {track_title}".strip(" -") if track_title else fallback_title,
            "duration_seconds": duration_seconds,
            "semantic_profile": semantic_profile,
            "metadata_confidence": metadata_confidence,
            "operator_intents": copy.deepcopy((persisted_show_plan or {}).get("operator_intents", [])),
            "venue_mode": venue_mode,
            "structure_markers": structure_markers,
            "show_sections": show_sections,
            "selection_mode": selection_mode,
            "selection_variance": selection_variance,
            "metadata_source": metadata_source,
            "show_source": show_source,
            "playhead_seconds": metadata.get("playhead_seconds"),
            "playing": metadata.get("playing"),
            "finished": metadata.get("finished"),
            "realtime": metadata.get("realtime", True),
            "speed": metadata.get("speed", 1.0),
        }

    return _bind


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


def _normalize_selection_mode(selection_mode: str | None) -> str:
    value = str(selection_mode or "procedural").strip().lower().replace("-", "_")
    return value if value in _SELECTION_MODES else "procedural"


def _normalize_selection_variance(value: Any | None) -> float:
    if value is None:
        return 0.0
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return 0.0
    return round(_clamp(normalized, 0.0, 1.0), 3)


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



def _fixture_capability_graph(venue_mode: str) -> dict[str, dict[str, Any]]:
    venue = _normalize_venue_mode(venue_mode)
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


def _compatible_laser_pattern(
    *,
    base_pattern: str,
    kind: str,
    context: str,
    profile: dict[str, Any],
    section_role: str,
    venue_mode: str,
) -> tuple[str, list[str]]:
    capability_graph = _fixture_capability_graph(venue_mode)
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
    fixture_role_map: dict[str, dict[str, Any]],
) -> None:
    section["lead_family"] = lead_family
    section["fixture_role_map"] = copy.deepcopy(fixture_role_map)
    cue_recipe = section.get("cue_recipe")
    if isinstance(cue_recipe, dict):
        cue_recipe["lead_family"] = lead_family
        cue_recipe["fixture_role_map"] = copy.deepcopy(fixture_role_map)
        families = cue_recipe.get("families")
        if isinstance(families, dict):
            for family, role_meta in fixture_role_map.items():
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
    venue = _normalize_venue_mode(venue_mode)
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
    venue = _normalize_venue_mode(venue_mode)
    preference = ["led", "mover", "wash", "laser"] if venue == "small_room_50_100" else ["laser", "led", "mover", "wash"]
    for family in preference:
        if enabled[family] and family != previous:
            return family
    return current or previous or "wash"


def _apply_show_section_validators(
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
        lead_family, fixture_role_map = _fixture_role_map(
            section_role=section_role,
            venue_mode=venue_mode,
            laser_enabled=bool(section.get("laser_enabled")),
            movers_enabled=bool(section.get("movers_enabled")),
            washes_enabled=bool(section.get("washes_enabled")),
            leds_enabled=bool(section.get("leds_enabled")),
            preferred_lead_family=current_lead,
        )
        _sync_section_role_state(section=section, lead_family=lead_family, fixture_role_map=fixture_role_map)
        _apply_strobe_policy(section, venue_mode)
        _apply_laser_policy(section, venue_mode)
        if section_role in {"drop_1", "drop_variation"}:
            previous_drop = section
    return validated


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
    stage = _pattern_stage(kind)
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
        geometry = _LASER_PATTERN_GEOMETRY.get(candidate, "fan")
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

        previous_geometry = _LASER_PATTERN_GEOMETRY.get(previous_pattern or "", "")
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


def _stable_seed(token: str) -> int:
    return int.from_bytes(_stable_digest(token)[:4], "big") & 0x7FFFFFFF


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
    candidates = _pattern_candidates(family=family, kind=kind, context=context, profile=profile)
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
    stage = _pattern_stage(kind)
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


def _ollama_section_selection(
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
) -> dict[str, str] | None:
    selection_variance = _normalize_selection_variance(selection_variance)
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
        limited = ranked[:_OLLAMA_CPU_MAX_CANDIDATES]
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
        "keep_alive": _OLLAMA_CPU_KEEP_ALIVE,
        "options": options,
    }
    request = urllib_request.Request(
        _ollama_generate_endpoint(),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(request, timeout=_OLLAMA_CPU_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib_error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        logger.warning(f"Local Ollama CPU selection failed: {exc}")
        return None

    parsed = _coerce_json_object(body.get("response", ""))
    if parsed is None:
        logger.warning("Local Ollama CPU selection returned invalid JSON")
        return None

    resolved: dict[str, str] = {}
    for family in ("laser", "mover", "wash", "led"):
        candidate = str(parsed.get(family, "")).strip()
        if candidate in family_candidates[family]:
            resolved[family] = candidate
    return resolved if resolved else None


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
    recent_patterns: list[str] | None = None,
    usage_count_by_pattern: dict[str, int] | None = None,
    semantic_profile: dict[str, Any] | None = None,
    selection_mode: str = "procedural",
    energy_scale: float = 0.6,
    selection_variance: float = 0.0,
) -> str:
    candidates = _pattern_candidates(family=family, kind=kind, context=context, profile=profile)
    if not candidates:
        raise RuntimeError(f"No pattern candidates for {family}:{kind}:{context}")
    if len(candidates) == 1:
        return candidates[0]
    selection_mode = _normalize_selection_mode(selection_mode)
    selection_variance = _normalize_selection_variance(selection_variance)
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
    stage = _pattern_stage(kind)
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


def _select_section_patterns(
    *,
    kind: str,
    context: str,
    profile: dict[str, Any],
    track_seed: str,
    marker_name: str,
    ordinal: int,
    previous_patterns: dict[str, str | None],
    pattern_history: dict[str, list[str]] | None,
    usage_count_by_family: dict[str, dict[str, int]] | None,
    semantic_profile: dict[str, Any] | None,
    selection_mode: str,
    energy_scale: float,
    selection_variance: float,
) -> dict[str, str]:
    return _showplan_select_section_patterns(
        kind=kind,
        context=context,
        profile=profile,
        track_seed=track_seed,
        marker_name=marker_name,
        ordinal=ordinal,
        previous_patterns=previous_patterns,
        pattern_history=pattern_history,
        usage_count_by_family=usage_count_by_family,
        semantic_profile=semantic_profile,
        selection_mode=selection_mode,
        energy_scale=energy_scale,
        selection_variance=selection_variance,
        normalize_selection_mode=_normalize_selection_mode,
        normalize_selection_variance=_normalize_selection_variance,
        pattern_candidates_fn=_pattern_candidates,
        ollama_section_selection_fn=_ollama_section_selection,
        select_pattern_fn=_select_pattern,
    )



def _default_show_sections(
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
    if not markers:
        markers = _auto_markers_for_duration(duration_seconds)

    seed = track_seed or "unknown-track"
    selection_mode = _normalize_selection_mode(selection_mode)
    selection_variance = _normalize_selection_variance(selection_variance)
    venue_mode = _normalize_venue_mode(venue_mode)
    venue_profile = _venue_profile(venue_mode)
    capability_graph = _fixture_capability_graph(venue_mode)
    _, profile = _creative_profile(seed, markers)
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
        intensity_multiplier = round(
            _clamp(float(intensity_multiplier) * float(venue_profile["intensity_scale"]), 0.15, 1.35),
            3,
        )
        motion_multiplier = round(
            _clamp(float(motion_multiplier) * float(venue_profile["motion_scale"]), 0.2, 1.4),
            3,
        )
        strobe_level = round(
            _clamp(float(strobe_level) * float(venue_profile["strobe_scale"]), 0.0, 1.0),
            3,
        )
        strobe_profile = _strobe_profile(
            kind=kind,
            context=context,
            track_seed=seed,
            ordinal=ordinal,
            base_level=strobe_level,
        )
        section_role = _normalize_section_role(
            kind=kind,
            marker_name=str(marker["name"]),
            context=context,
            ordinal=ordinal,
            total_of_kind=total_counts.get(kind, 1),
        )
        section_patterns = _select_section_patterns(
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
        laser_pattern, laser_capability_notes = _compatible_laser_pattern(
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
        laser_enabled, movers_enabled, washes_enabled, leds_enabled = _fixture_enablement(
            kind=kind,
            context=context,
            profile=profile,
            track_seed=seed,
            ordinal=ordinal,
        )
        lead_family, fixture_role_map = _fixture_role_map(
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
            next_context = _transition_context(
                previous_kind=kind,
                kind=next_kind_value,
                next_kind=str(ordered[index + 2]["kind"]) if index + 2 < len(ordered) else None,
                ordinal=next_ordinal,
                total_of_kind=next_total_of_kind,
            )
            next_section_role = _normalize_section_role(
                kind=next_kind_value,
                marker_name=str(next_marker["name"]),
                context=next_context,
                ordinal=next_ordinal,
                total_of_kind=next_total_of_kind,
            )
        transition_intent = _transition_intent(
            section_role=section_role,
            context=context,
            previous_role=previous_section_role,
            next_role=next_section_role,
        )
        cue_family_id = _cue_family_id(section_role, lead_family, venue_mode)
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
        cue_recipe = _cue_recipe(
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
            venue_profile=venue_profile,
            transition_intent=transition_intent,
            cue_family_id=cue_family_id,
            lead_family=lead_family,
            fixture_role_map=fixture_role_map,
            capability_graph=capability_graph,
            capability_notes=capability_notes,
            metadata_confidence=metadata_confidence,
        )
        sections.append(
            {
                "generator_version": _SHOW_SECTION_GENERATOR_VERSION,
                "id": f"section_{index:03d}",
                "label": str(marker["name"]),
                "kind": kind,
                "section_role": section_role,
                "venue_mode": venue_mode,
                "venue_profile": copy.deepcopy(venue_profile),
                "cue_family_id": cue_family_id,
                "lead_family": lead_family,
                "fixture_role_map": copy.deepcopy(fixture_role_map),
                "transition_intent": copy.deepcopy(transition_intent),
                "fixture_capability_graph": copy.deepcopy(capability_graph),
                "capability_notes": list(capability_notes),
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
                "laser_program": _laser_program(
                    track_seed=seed,
                    base_pattern=laser_pattern,
                    kind=kind,
                    context=context,
                    ordinal=ordinal,
                    profile=profile,
                    venue_mode=venue_mode,
                ),
                "cue_recipe": cue_recipe,
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
        previous_section_role = section_role
    validated_sections = _apply_show_section_validators(sections, venue_mode=venue_mode)
    return _decorate_show_sections_with_motifs(validated_sections)


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

    An autonomous lighting control system built on a deterministic execution
    pipeline,
    combining real-time audio analysis, MIDI telemetry, and computer vision
    to create structure-aware, music-reactive light shows.
    """
    ctx.ensure_object(dict)

    # Configure logging
    log_level = logging.DEBUG if debug else logging.INFO
    configure_logging(log_level)

    ctx.obj["debug"] = debug
    ctx.obj["config_path"] = Path(config) if config else None


@cli.group("catalog")
def catalog_cli() -> None:
    """Build and inspect offline-ready show catalogs."""


@catalog_cli.command("build")
@click.argument("music_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--rekordbox-xml",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Optional Rekordbox XML export used to import markers during catalog build",
)
@click.option(
    "--selection-mode",
    type=click.Choice(sorted(_SELECTION_MODES), case_sensitive=False),
    default="ai_assisted",
    show_default=True,
    help="Selection engine used while generating cataloged show sections",
)
@click.option(
    "--selection-variance",
    default=0.2,
    type=float,
    show_default=True,
    help="Exploration value used for the primary cataloged show plan",
)
@click.option(
    "--venue-mode",
    type=click.Choice(sorted(_VENUE_MODES), case_sensitive=False),
    default="small_room_50_100",
    show_default=True,
    help="Supported venue profile used while compiling show sections",
)
@click.option(
    "--ollama-model",
    help="Optional Ollama model override used when --selection-mode=local_ollama_cpu",
)
@click.option(
    "--ollama-host",
    help="Optional Ollama host override, for example http://127.0.0.1:11500",
)
@click.option(
    "--ollama-use-gpu/--ollama-cpu",
    default=False,
    show_default=True,
    help="Allow Ollama to use GPU layers during offline catalog builds",
)
@click.option(
    "--web-enrichment/--no-web-enrichment",
    default=True,
    show_default=True,
    help="Fetch advisory web metadata from Apple Music, Beatport, and Bandcamp during catalog build",
)
@click.option("--limit", type=int, help="Optional limit on the number of audio files to catalog")
def catalog_build(
    music_path: Path,
    rekordbox_xml: Path | None,
    selection_mode: str,
    selection_variance: float,
    venue_mode: str,
    ollama_model: str | None,
    ollama_host: str | None,
    ollama_use_gpu: bool,
    web_enrichment: bool,
    limit: int | None,
) -> None:
    """Build JSON show catalogs for a music file or directory."""
    from photonic_synesthesia.integrations import load_rekordbox_track
    from photonic_synesthesia.integrations.show_catalog import save_show_catalog

    selection_mode = _normalize_selection_mode(selection_mode)
    selection_variance = _normalize_selection_variance(selection_variance)
    venue_mode = _normalize_venue_mode(venue_mode)
    rekordbox_source = rekordbox_xml or _discover_rekordbox_xml()
    audio_files = _discover_audio_files(music_path)
    if limit is not None and limit >= 0:
        audio_files = audio_files[:limit]
    if not audio_files:
        click.echo("No supported audio files found for catalog build.", err=True)
        raise SystemExit(1)

    previous_ollama_model = os.environ.get("PHOTONIC_OLLAMA_MODEL")
    previous_ollama_host = os.environ.get("PHOTONIC_OLLAMA_HOST")
    previous_ollama_num_gpu = os.environ.get("PHOTONIC_OLLAMA_NUM_GPU")
    if selection_mode == "local_ollama_cpu" and ollama_model:
        os.environ["PHOTONIC_OLLAMA_MODEL"] = ollama_model
    if selection_mode == "local_ollama_cpu" and ollama_host:
        os.environ["PHOTONIC_OLLAMA_HOST"] = ollama_host
    if selection_mode == "local_ollama_cpu":
        os.environ["PHOTONIC_OLLAMA_NUM_GPU"] = "-1" if ollama_use_gpu else "0"
    try:
        click.echo(
            f"Cataloging {len(audio_files)} track(s) with {selection_mode} at exploration {selection_variance:.2f}"
        )
        click.echo(f"Venue mode: {venue_mode}")
        if selection_mode == "local_ollama_cpu":
            click.echo(f"Ollama model: {_ollama_model_name()}")
            click.echo(f"Ollama host: {_ollama_host()}")
            click.echo(f"Ollama GPU mode: {'auto' if _ollama_num_gpu_option() is None else 'disabled'}")
        if rekordbox_source is not None:
            click.echo(f"Rekordbox XML: {rekordbox_source}")

        failures = 0
        for index, audio_file in enumerate(audio_files, start=1):
            try:
                duration_seconds = _audio_file_duration_seconds(audio_file)
                matched_rekordbox_track = (
                    load_rekordbox_track(
                        rekordbox_source,
                        audio_file,
                        audio_duration_seconds=duration_seconds,
                    )
                    if rekordbox_source is not None
                    else None
                )
                structure_markers = [
                    {
                        "name": marker.name,
                        "kind": marker.kind,
                        "start_seconds": round(marker.start_seconds, 3),
                        "energy_hint": marker.energy_hint,
                    }
                    for marker in (matched_rekordbox_track.markers if matched_rekordbox_track else [])
                ]
                track_title = matched_rekordbox_track.title if matched_rekordbox_track else audio_file.stem
                track_artist = matched_rekordbox_track.artist if matched_rekordbox_track else ""
                track_key = (
                    f"{track_artist or ''}|{track_title}".strip("|")
                    if track_title
                    else audio_file.stem
                ) or audio_file.stem
                enrichment = (
                    _fetch_catalog_web_enrichment(
                        track_title=track_title,
                        track_artist=track_artist,
                        duration_seconds=duration_seconds,
                    )
                    if web_enrichment
                    else {}
                )
                payload = _build_show_catalog_entry(
                    audio_file=audio_file,
                    duration_seconds=duration_seconds,
                    structure_markers=structure_markers,
                    track_key=track_key,
                    track_title=track_title,
                    track_artist=track_artist,
                    selection_mode=selection_mode,
                    selection_variance=selection_variance,
                    venue_mode=venue_mode,
                    rekordbox_source=rekordbox_source,
                    rekordbox_track_id=matched_rekordbox_track.track_id if matched_rekordbox_track else "",
                    rekordbox_average_bpm=matched_rekordbox_track.average_bpm if matched_rekordbox_track else None,
                    web_enrichment=enrichment,
                )
                saved_path = save_show_catalog(track_key, payload)
                click.echo(f"[{index}/{len(audio_files)}] {track_key} -> {saved_path}")
            except Exception as exc:  # pragma: no cover - surfaced in CLI output
                failures += 1
                click.echo(f"[{index}/{len(audio_files)}] Failed {audio_file}: {exc}", err=True)

        if failures:
            click.echo(f"Catalog build completed with {failures} failure(s).", err=True)
            raise SystemExit(1)
        click.echo("Catalog build complete.")
    finally:
        if selection_mode == "local_ollama_cpu":
            if previous_ollama_model is None:
                os.environ.pop("PHOTONIC_OLLAMA_MODEL", None)
            else:
                os.environ["PHOTONIC_OLLAMA_MODEL"] = previous_ollama_model
            if previous_ollama_host is None:
                os.environ.pop("PHOTONIC_OLLAMA_HOST", None)
            else:
                os.environ["PHOTONIC_OLLAMA_HOST"] = previous_ollama_host
            if previous_ollama_num_gpu is None:
                os.environ.pop("PHOTONIC_OLLAMA_NUM_GPU", None)
            else:
                os.environ["PHOTONIC_OLLAMA_NUM_GPU"] = previous_ollama_num_gpu


@catalog_cli.command("export-model-payloads")
@click.argument("output_path", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--track-key", "track_keys", multiple=True, help="Optional track key filter; may be passed multiple times")
@click.option("--limit", type=int, help="Optional limit on the number of exported catalog entries")
def catalog_export_model_payloads(
    output_path: Path,
    track_keys: tuple[str, ...],
    limit: int | None,
) -> None:
    """Export compact catalog model payloads as JSONL for external evaluators."""
    from photonic_synesthesia.integrations import list_show_catalog_paths

    normalized_track_keys = {str(track_key).strip() for track_key in track_keys if str(track_key).strip()}
    exported_rows: list[str] = []
    catalog_paths = list_show_catalog_paths()
    if normalized_track_keys:
        filtered_paths: list[Path] = []
        for path in catalog_paths:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if str(payload.get("track_key") or "").strip() in normalized_track_keys:
                filtered_paths.append(path)
        catalog_paths = filtered_paths
    if limit is not None and limit >= 0:
        catalog_paths = catalog_paths[:limit]
    if not catalog_paths:
        click.echo("No matching show catalogs found to export.", err=True)
        raise SystemExit(1)

    for path in catalog_paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            click.echo(f"Skipping unreadable catalog {path}: {exc}", err=True)
            continue
        model_payload = payload.get("model_payload")
        if not isinstance(model_payload, dict):
            click.echo(f"Skipping catalog without model_payload: {path}", err=True)
            continue
        exported_rows.append(json.dumps(model_payload, sort_keys=True))

    if not exported_rows:
        click.echo("No exportable model payloads found.", err=True)
        raise SystemExit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(exported_rows) + "\n", encoding="utf-8")
    click.echo(f"Exported {len(exported_rows)} model payload(s) to {output_path}")


@cli.command()
@click.option("--mock", is_flag=True, help="Use mock sensors (no hardware)")
@click.option("--fps", default=50.0, help="Target frames per second")
@click.option("--web", "web_mode", is_flag=True, help="Serve the control-plane website in the same process")
@click.option("--web-host", default="127.0.0.1", help="Embedded web server host")
@click.option("--web-port", default=8000, type=int, help="Embedded web server port")
@click.pass_context
def run(ctx: click.Context, mock: bool, fps: float, web_mode: bool, web_host: str, web_port: int) -> None:
    """Run the photonic synesthesia system."""
    from photonic_synesthesia.core.config import Settings
    from photonic_synesthesia.graph import build_photonic_graph
    from photonic_synesthesia.platform import (
        ControlPlaneStateService,
        PlaybackContext,
        clear_shared_control_plane_service,
        clear_shared_playback_context,
        set_shared_control_plane_service,
        set_shared_playback_context,
    )
    from photonic_synesthesia.ui.web_panel import serve_in_thread

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
    web_server = None
    web_thread = None
    control_plane_service = set_shared_control_plane_service(ControlPlaneStateService())
    playback_context: PlaybackContext | None = None

    def _shutdown(signum: int, frame: object) -> None:
        """Signal handler: ask the graph to stop cleanly."""
        if graph is not None:
            graph.stop()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        rekordbox_source = _discover_rekordbox_xml()
        metadata_binding = _build_track_metadata_binding_callback(
            rekordbox_xml=rekordbox_source,
            fallback_track_key="live-pro-dj-link",
            fallback_title="Live Track",
            fallback_duration_seconds=0.0,
            fallback_venue_mode="small_room_50_100",
        )
        if web_mode:
            def _regenerate_live_show_sections(mode: str, variance: float) -> list[dict[str, Any]]:
                if playback_context is None:
                    return []
                binding = metadata_binding(
                    {
                        "track_title": playback_context.track_title,
                        "track_artist": playback_context.track_artist,
                        "duration_seconds": playback_context.duration_seconds,
                        "selection_mode": mode,
                        "selection_variance": variance,
                        "metadata_source": playback_context.metadata_source,
                        "venue_mode": "small_room_50_100",
                        "metadata_confidence": copy.deepcopy(playback_context.metadata_confidence),
                    }
                )
                return list(binding.get("show_sections", []))

            playback_context = set_shared_playback_context(
                PlaybackContext(
                    file_path="",
                    file_name="Live Track",
                    duration_seconds=0.0,
                    track_title="Live Track",
                    track_artist="",
                    track_key="live-pro-dj-link",
                    venue_mode="small_room_50_100",
                    metadata_source="pro_dj_link",
                    operator_intents=[],
                    _save_callback=_show_plan_payload_saver("live-pro-dj-link"),
                    _regenerate_callback=_regenerate_live_show_sections,
                    _metadata_bind_callback=metadata_binding,
                )
            )
            web_server, web_thread = serve_in_thread(
                services=control_plane_service,
                host=web_host,
                port=web_port,
            )
            click.echo(f"Web UI: http://{web_host}:{web_port}/")

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
        if web_server is not None:
            web_server.should_exit = True
            if web_thread is not None and web_thread.is_alive():
                web_thread.join(timeout=5.0)
        clear_shared_control_plane_service()
        clear_shared_playback_context()


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
@click.option(
    "--venue-mode",
    type=click.Choice(sorted(_VENUE_MODES), case_sensitive=False),
    default="small_room_50_100",
    show_default=True,
    help="Supported venue profile used while generating or refreshing show sections",
)
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
    venue_mode: str,
) -> None:
    """Run the graph against an audio file such as MP3 or WAV."""
    from photonic_synesthesia.core.config import Settings
    from photonic_synesthesia.graph import build_photonic_graph
    from photonic_synesthesia.graph.nodes.audio_file_sense import AudioFileSenseNode
    from photonic_synesthesia.integrations import load_rekordbox_track
    from photonic_synesthesia.integrations.show_plans import ilda_export_path
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
    venue_mode = _normalize_venue_mode(venue_mode)

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
            or (
                settings.ilda.transport_type == "ild"
                and transport_source != ParameterSource.DEFAULT
            )
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
    click.echo(f"Venue Mode: {venue_mode}")
    click.echo(f"Target FPS: {fps}")
    click.echo(f"Chunk Size: {chunk_size} samples")
    click.echo()
    if (
        settings.ilda.transport_type == "ild"
        and ilda_export_path_override is None
    ):
        settings.ilda.export_path = ilda_export_path(audio_file.stem)

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
        audio_node.start()

        matched_rekordbox_track = None
        rekordbox_source = rekordbox_xml or _discover_rekordbox_xml()
        if rekordbox_source is not None:
            matched_rekordbox_track = load_rekordbox_track(
                rekordbox_source,
                audio_file,
                audio_duration_seconds=audio_node.duration_seconds,
            )
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

        structure_markers = [
            {
                "name": marker.name,
                "kind": marker.kind,
                "start_seconds": round(marker.start_seconds, 3),
                "energy_hint": marker.energy_hint,
            }
            for marker in (matched_rekordbox_track.markers if matched_rekordbox_track else [])
        ]

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
        persisted_show_plan, show_source = _load_precomputed_show_plan(track_key)
        if not structure_markers and persisted_show_plan and isinstance(
            persisted_show_plan.get("structure_markers"), list
        ):
            structure_markers = [
                dict(marker) for marker in persisted_show_plan.get("structure_markers", [])
            ]
        selection_mode = _normalize_selection_mode(
            persisted_show_plan.get("selection_mode")
            if persisted_show_plan
            else "procedural"
        )
        selection_variance = _normalize_selection_variance(
            persisted_show_plan.get("selection_variance")
            if persisted_show_plan
            else 0.0
        )
        semantic_profile = copy.deepcopy((persisted_show_plan or {}).get("semantic_profile", {}))
        metadata_confidence = copy.deepcopy((persisted_show_plan or {}).get("metadata_confidence", {}))
        if not metadata_confidence:
            metadata_confidence = _metadata_confidence(
                structure_markers=structure_markers,
                metadata_source="file_playback",
                rekordbox_track_id=matched_rekordbox_track.track_id if matched_rekordbox_track else "",
                rekordbox_average_bpm=matched_rekordbox_track.average_bpm if matched_rekordbox_track else None,
                web_enrichment=None,
                matched_rekordbox_track=matched_rekordbox_track is not None,
            )
        active_show_sections = _resolve_show_sections(
            persisted_show_plan,
            structure_markers,
            audio_node.duration_seconds,
            track_seed=track_key,
            semantic_profile=semantic_profile,
            selection_mode=selection_mode,
            selection_variance=selection_variance,
            venue_mode=(
                persisted_show_plan.get("venue_mode")
                if persisted_show_plan and persisted_show_plan.get("venue_mode") is not None
                else venue_mode
            ),
            metadata_confidence=metadata_confidence,
        )
        venue_mode = _normalize_venue_mode(
            persisted_show_plan.get("venue_mode")
            if persisted_show_plan and persisted_show_plan.get("venue_mode") is not None
            else venue_mode
        )
        if (
            settings.ilda.transport_type == "ild"
            and ilda_export_path_override is None
        ):
            settings.ilda.export_path = ilda_export_path(track_key)

        def _regenerate_show_sections(mode: str, variance: float) -> list[dict[str, Any]]:
            return _default_show_sections(
                structure_markers,
                audio_node.duration_seconds,
                track_seed=track_key,
                semantic_profile=semantic_profile,
                selection_mode=mode,
                selection_variance=variance,
                venue_mode=venue_mode,
                metadata_confidence=metadata_confidence,
            )

        if web_mode:
            playback_context = set_shared_playback_context(
                PlaybackContext(
                    file_path=str(audio_file),
                    file_name=audio_file.name,
                    duration_seconds=audio_node.duration_seconds,
                    track_title=matched_rekordbox_track.title if matched_rekordbox_track else audio_file.stem,
                    track_artist=matched_rekordbox_track.artist if matched_rekordbox_track else "",
                    track_key=track_key,
                    venue_mode=venue_mode,
                    metadata_confidence=copy.deepcopy(metadata_confidence),
                    operator_intents=copy.deepcopy((persisted_show_plan or {}).get("operator_intents", [])),
                    waveform=audio_node.waveform_preview(),
                    structure_markers=structure_markers,
                    show_sections=active_show_sections,
                    selection_mode=selection_mode,
                    selection_variance=selection_variance,
                    show_source=show_source,
                    show_plan_path=str(
                        persisted_show_plan.get("saved_path", "")
                        if persisted_show_plan and persisted_show_plan.get("saved_path")
                        else ""
                    ),
                    ilda_transport_type=settings.ilda.transport_type,
                    ilda_export_path=str(settings.ilda.export_path or ""),
                    hardware_warnings=hardware_warnings,
                    _seek_callback=audio_node.seek,
                    _save_callback=_show_plan_payload_saver(track_key),
                    _metadata_bind_callback=_build_track_metadata_binding_callback(
                        rekordbox_xml=rekordbox_source,
                        fallback_track_key=track_key,
                        fallback_title=matched_rekordbox_track.title if matched_rekordbox_track else audio_file.stem,
                        fallback_artist=matched_rekordbox_track.artist if matched_rekordbox_track else "",
                        fallback_duration_seconds=audio_node.duration_seconds,
                        fallback_venue_mode=venue_mode,
                    ),
                    _regenerate_callback=_regenerate_show_sections,
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


def _build_show_catalog_entry(**kwargs: Any) -> dict[str, Any]:
    return _showplan_build_show_catalog_entry(
        **kwargs,
        normalize_selection_mode=_normalize_selection_mode,
        normalize_selection_variance=_normalize_selection_variance,
        normalize_venue_mode=_normalize_venue_mode,
        metadata_confidence_fn=_metadata_confidence,
        build_semantic_profile_fn=_build_semantic_profile,
        default_show_sections_fn=_default_show_sections,
        decorate_show_sections_with_motifs_fn=_decorate_show_sections_with_motifs,
        recent_catalog_entries_fn=_recent_catalog_entries,
        show_fingerprint_fn=_show_fingerprint,
        anti_template_validation_fn=_anti_template_validation,
        motif_registry_fn=_motif_registry,
        scorer_bundle_fn=_scorer_bundle,
        preview_artifacts_fn=_preview_artifacts,
        build_catalog_model_payload_fn=_build_catalog_model_payload,
        ollama_model_name_fn=_ollama_model_name,
        ollama_num_gpu_option_fn=_ollama_num_gpu_option,
        catalog_version=_CATALOG_VERSION,
        show_section_generator_version=_SHOW_SECTION_GENERATOR_VERSION,
        laser_program_version=_LASER_PROGRAM_VERSION,
    )


def _resolve_show_sections(
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
) -> list[dict[str, Any]]:
    return _showplan_resolve_show_sections(
        persisted_show_plan,
        markers,
        duration_seconds,
        track_seed=track_seed,
        semantic_profile=semantic_profile,
        selection_mode=selection_mode,
        selection_variance=selection_variance,
        venue_mode=venue_mode,
        metadata_confidence=metadata_confidence,
        normalize_selection_mode=_normalize_selection_mode,
        normalize_selection_variance=_normalize_selection_variance,
        normalize_venue_mode=_normalize_venue_mode,
        default_show_sections_fn=_default_show_sections,
        laser_program_version=_LASER_PROGRAM_VERSION,
        show_section_generator_version=_SHOW_SECTION_GENERATOR_VERSION,
        cue_recipe_version=_CUE_RECIPE_VERSION,
    )


def main() -> None:
    """Entry point for the CLI."""
    cli(obj={})


if __name__ == "__main__":
    main()
