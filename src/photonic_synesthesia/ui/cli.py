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
from datetime import UTC, datetime
from hashlib import sha1
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

import click
from click.core import ParameterSource

from photonic_synesthesia import __version__
from photonic_synesthesia.core.logging import configure_logging, get_logger

logger = get_logger(__name__)

_LASER_PROGRAM_VERSION = 3
_SHOW_SECTION_GENERATOR_VERSION = 3
_SEMANTIC_PROFILE_VERSION = 1
_CUE_RECIPE_VERSION = 1
_SELECTION_MODES = {"procedural", "ai_assisted", "local_ollama_cpu"}
_OLLAMA_CPU_MODEL = "qwen2.5:1.5b"
_OLLAMA_DEFAULT_HOST = "http://127.0.0.1:11434"
_OLLAMA_CPU_KEEP_ALIVE = "10m"
_OLLAMA_CPU_TIMEOUT_SECONDS = 6.0
_OLLAMA_CPU_MAX_CANDIDATES = 6
_CATALOG_VERSION = 4
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


def _build_show_catalog_entry(
    *,
    audio_file: Path,
    duration_seconds: float,
    structure_markers: list[dict[str, Any]],
    track_key: str,
    track_title: str,
    track_artist: str,
    selection_mode: str,
    selection_variance: float,
    rekordbox_source: Path | None,
    rekordbox_track_id: str = "",
    rekordbox_average_bpm: float | None = None,
    web_enrichment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selection_mode = _normalize_selection_mode(selection_mode)
    selection_variance = _normalize_selection_variance(selection_variance)
    semantic_profile = _build_semantic_profile(
        track_title=track_title,
        track_artist=track_artist,
        duration_seconds=duration_seconds,
        structure_markers=structure_markers,
        rekordbox_average_bpm=rekordbox_average_bpm,
        web_enrichment=web_enrichment,
    )
    show_sections = _default_show_sections(
        structure_markers,
        duration_seconds,
        track_seed=track_key,
        selection_mode=selection_mode,
        selection_variance=selection_variance,
    )
    alternate_variances = {
        "tight": 0.0,
        "balanced": 0.35,
        "wild": 0.75,
    }
    alternates = {
        label: {
            "selection_mode": selection_mode,
            "selection_variance": variance,
            "show_sections": _default_show_sections(
                structure_markers,
                duration_seconds,
                track_seed=track_key,
                selection_mode=selection_mode,
                selection_variance=variance,
            ),
        }
        for label, variance in alternate_variances.items()
    }
    model_payload = _build_catalog_model_payload(
        track_key=track_key,
        track_title=track_title,
        track_artist=track_artist,
        duration_seconds=duration_seconds,
        structure_markers=structure_markers,
        show_sections=show_sections,
        selection_mode=selection_mode,
        selection_variance=selection_variance,
        rekordbox_track_id=rekordbox_track_id,
        rekordbox_average_bpm=rekordbox_average_bpm,
        semantic_profile=semantic_profile,
        web_enrichment=web_enrichment,
    )
    return {
        "catalog_version": _CATALOG_VERSION,
        "track_key": track_key,
        "track_title": track_title,
        "track_artist": track_artist,
        "file_name": audio_file.name,
        "file_path": str(audio_file),
        "duration_seconds": round(float(duration_seconds), 3),
        "structure_markers": [dict(marker) for marker in structure_markers],
        "selection_mode": selection_mode,
        "selection_variance": selection_variance,
        "semantic_profile": semantic_profile,
        "show_sections": show_sections,
        "alternates": alternates,
        "model_payload": model_payload,
        "source": {
            "rekordbox_xml": str(rekordbox_source) if rekordbox_source else "",
            "rekordbox_track_id": rekordbox_track_id,
            "average_bpm": rekordbox_average_bpm,
        },
        "web_enrichment": copy.deepcopy(web_enrichment) if isinstance(web_enrichment, dict) else {},
        "provenance": {
            "generated_at": datetime.now(UTC).isoformat(),
            "planner_version": _SHOW_SECTION_GENERATOR_VERSION,
            "laser_program_version": _LASER_PROGRAM_VERSION,
            "selection_mode": selection_mode,
            "selection_variance": selection_variance,
            "ollama_model": _ollama_model_name() if selection_mode == "local_ollama_cpu" else "",
            "ollama_num_gpu": _ollama_num_gpu_option() if selection_mode == "local_ollama_cpu" else "",
            "generator_host": socket.gethostname(),
            "web_enrichment_version": int((web_enrichment or {}).get("version", 0) or 0),
        },
    }


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
    markers = (
        sorted([dict(marker) for marker in structure_markers], key=lambda item: float(item.get("start_seconds", 0.0)))
        if structure_markers
        else _auto_markers_for_duration(duration_seconds)
    )
    web_summary = copy.deepcopy((web_enrichment or {}).get("summary", {}))
    web_confidence = copy.deepcopy((web_enrichment or {}).get("confidence", {}))
    counts_by_kind: dict[str, int] = {}
    energy_values: list[float] = []
    first_drop_seconds: float | None = None
    first_breakdown_seconds: float | None = None
    for marker in markers:
        kind = str(marker.get("kind") or "marker")
        counts_by_kind[kind] = counts_by_kind.get(kind, 0) + 1
        start_seconds = float(marker.get("start_seconds") or 0.0)
        if kind == "drop" and first_drop_seconds is None:
            first_drop_seconds = start_seconds
        if kind == "breakdown" and first_breakdown_seconds is None:
            first_breakdown_seconds = start_seconds
        energy_hint = marker.get("energy_hint")
        if energy_hint is not None:
            energy_values.append(float(energy_hint))

    duration = max(1.0, float(duration_seconds))
    drop_ratio = 0.0 if first_drop_seconds is None else max(0.0, min(1.0, first_drop_seconds / duration))
    if first_drop_seconds is None:
        arc_shape = "unresolved"
    elif drop_ratio <= 0.2:
        arc_shape = "front_loaded"
    elif drop_ratio <= 0.42:
        arc_shape = "balanced_wave"
    else:
        arc_shape = "patient_arc"

    tempo_band = "unknown"
    if rekordbox_average_bpm is not None:
        bpm_value = float(rekordbox_average_bpm)
        if bpm_value < 116:
            tempo_band = "slow_club"
        elif bpm_value < 124:
            tempo_band = "midtempo_club"
        elif bpm_value < 130:
            tempo_band = "peak_progressive"
        else:
            tempo_band = "high_energy"

    return {
        "version": _SEMANTIC_PROFILE_VERSION,
        "track_identity": {
            "title": track_title,
            "artist": track_artist,
            "duration_seconds": round(duration, 3),
            "average_bpm": rekordbox_average_bpm,
            "tempo_band": tempo_band,
        },
        "genre_hints": [
            value
            for value in [str(web_summary.get("genre_primary") or "").strip(), *[str(item).strip() for item in web_summary.get("genre_secondary", [])]]
            if value
        ],
        "descriptors": [str(item) for item in web_summary.get("editorial_descriptors", []) if str(item).strip()],
        "style_bias": copy.deepcopy(web_summary.get("style_bias", {})),
        "structure_summary": {
            "section_count": len(markers),
            "counts_by_kind": counts_by_kind,
            "has_rekordbox_markers": bool(structure_markers),
            "first_drop_seconds": None if first_drop_seconds is None else round(first_drop_seconds, 3),
            "first_breakdown_seconds": None if first_breakdown_seconds is None else round(first_breakdown_seconds, 3),
            "drop_ratio": round(drop_ratio, 3),
            "arc_shape": arc_shape,
            "average_energy_hint": round(sum(energy_values) / len(energy_values), 3) if energy_values else None,
        },
        "confidence": {
            "web": copy.deepcopy(web_confidence),
            "structure": {
                "markers_present": bool(structure_markers),
                "section_count": len(markers),
            },
        },
    }


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


def _cue_recipe_family(
    *,
    family: str,
    pattern: str,
    stage: str,
    timing_master: str,
    enabled: bool,
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
    }
    if family == "laser":
        payload["zone_policy"] = zone_policy
    return payload


def _cue_recipe(
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
) -> dict[str, Any]:
    stage = _pattern_stage(kind)
    timing_master = _cue_recipe_timing_master(stage, context)
    zone_policy = _laser_zone_policy(kind, context)
    return {
        "version": _CUE_RECIPE_VERSION,
        "intent": context,
        "stage": stage,
        "transition_strategy": _cue_recipe_transition_strategy(stage, context),
        "timing_master": timing_master,
        "families": {
            "laser": _cue_recipe_family(
                family="laser",
                pattern=laser_pattern,
                stage=stage,
                timing_master=timing_master,
                enabled=laser_enabled,
                zone_policy=zone_policy,
            ),
            "mover": _cue_recipe_family(
                family="mover",
                pattern=mover_pattern,
                stage=stage,
                timing_master=timing_master,
                enabled=movers_enabled,
            ),
            "wash": _cue_recipe_family(
                family="wash",
                pattern=wash_pattern,
                stage=stage,
                timing_master=timing_master,
                enabled=washes_enabled,
            ),
            "led": _cue_recipe_family(
                family="led",
                pattern=led_pattern,
                stage=stage,
                timing_master=timing_master,
                enabled=leds_enabled,
            ),
        },
    }


def _model_payload_candidates(
    *,
    family: str,
    kind: str,
    context: str,
    profile: dict[str, Any],
    selected_pattern: str = "",
) -> list[str]:
    candidates = _pattern_candidates(
        family=family,
        kind=kind,
        context=context,
        profile=profile,
    )
    limited = list(candidates[:_OLLAMA_CPU_MAX_CANDIDATES])
    if selected_pattern and selected_pattern not in limited and selected_pattern in candidates:
        limited.append(selected_pattern)
    return limited


def _build_catalog_model_payload(
    *,
    track_key: str,
    track_title: str,
    track_artist: str,
    duration_seconds: float,
    structure_markers: list[dict[str, Any]],
    show_sections: list[dict[str, Any]],
    selection_mode: str,
    selection_variance: float,
    rekordbox_track_id: str = "",
    rekordbox_average_bpm: float | None = None,
    semantic_profile: dict[str, Any] | None = None,
    web_enrichment: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
                "stage": _pattern_stage(kind),
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
        },
        "planner": {
            "creative_profile": profile_name,
            "energy_profile": str(profile.get("energy_profile") or ""),
            "semantic_profile": copy.deepcopy(semantic_profile or {}),
            "style_bias": copy.deepcopy(web_summary.get("style_bias", {})),
            "genre_primary": str(web_summary.get("genre_primary") or ""),
            "genre_secondary": list(web_summary.get("genre_secondary") or []),
            "editorial_descriptors": list(web_summary.get("editorial_descriptors") or []),
            "tags": list(web_summary.get("tags") or []),
            "web_confidence": copy.deepcopy(web_confidence),
        },
        "sections": payload_sections,
    }


def _build_track_metadata_binding_callback(
    *,
    rekordbox_xml: Path | None,
    fallback_track_key: str,
    fallback_title: str,
    fallback_artist: str = "",
    fallback_duration_seconds: float = 0.0,
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
        show_sections = _resolve_show_sections(
            persisted_show_plan,
            structure_markers,
            duration_seconds,
            track_seed=track_key,
            selection_mode=selection_mode,
            selection_variance=selection_variance,
        )
        return {
            "track_title": track_title,
            "track_artist": track_artist,
            "track_key": track_key,
            "file_name": f"{track_artist} - {track_title}".strip(" -") if track_title else fallback_title,
            "duration_seconds": duration_seconds,
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


def _normalize_selection_mode(selection_mode: str | None) -> str:
    value = str(selection_mode or "procedural").strip().lower().replace("-", "_")
    return value if value in _SELECTION_MODES else "procedural"


def _normalize_selection_variance(value: Any | None) -> float:
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return 0.0
    return round(_clamp(normalized, 0.0, 1.0), 3)


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
        return "build_cycle"
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
) -> float:
    stage = _pattern_stage(kind)
    candidate_index = candidates.index(candidate)
    score = max(0.0, 1.9 - candidate_index * 0.16)
    score += (_stable_float(f"{track_seed}:{family}:{kind}:{context}:{ordinal}:{marker_name}:{candidate}") - 0.5) * 0.44

    if candidate == previous_pattern:
        score -= 1.5

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
    ordered_nonrepeat = [candidate for candidate in ordered if candidate != previous_pattern] or ordered
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
    selection_mode: str,
    energy_scale: float,
    selection_variance: float,
) -> dict[str, str]:
    normalized_mode = _normalize_selection_mode(selection_mode)
    selection_variance = _normalize_selection_variance(selection_variance)
    resolved: dict[str, str] = {}
    ollama_choices: dict[str, str] | None = None
    family_candidates = {
        family: set(_pattern_candidates(family=family, kind=kind, context=context, profile=profile))
        for family in ("laser", "mover", "wash", "led")
    }
    if normalized_mode == "local_ollama_cpu":
        ollama_choices = _ollama_section_selection(
            kind=kind,
            context=context,
            profile=profile,
            track_seed=track_seed,
            marker_name=marker_name,
            ordinal=ordinal,
            energy_scale=energy_scale,
            previous_patterns=previous_patterns,
            selection_variance=selection_variance,
        )
    for family in ("laser", "mover", "wash", "led"):
        if (
            ollama_choices
            and ollama_choices.get(family)
            and ollama_choices[family] in family_candidates[family]
        ):
            resolved[family] = ollama_choices[family]
            continue
        fallback_mode = "procedural" if normalized_mode == "local_ollama_cpu" else normalized_mode
        resolved[family] = _select_pattern(
            family=family,
            kind=kind,
            context=context,
            profile=profile,
            track_seed=track_seed,
            marker_name=marker_name,
            ordinal=ordinal,
            previous_pattern=previous_patterns.get(family),
            selection_mode=fallback_mode,
            energy_scale=energy_scale,
            selection_variance=selection_variance,
        )
    return resolved


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
    geometry_family = _LASER_PATTERN_GEOMETRY.get(base_pattern, "fan")
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


def _laser_zone_policy(kind: str, context: str) -> str:
    stage = _pattern_stage(kind)
    if stage == "breakdown":
        return "overhead_only"
    if context == "drop_launch":
        return "crowd_punctuate"
    if stage == "build":
        return "mixed_air"
    if stage == "drop":
        return "mixed_air"
    return "overhead_bias"


def _laser_program(
    *,
    track_seed: str,
    base_pattern: str,
    kind: str,
    context: str,
    ordinal: int,
    profile: dict[str, Any],
) -> dict[str, Any]:
    def _rotate_patterns(patterns: list[str], token: str) -> list[str]:
        if len(patterns) <= 1:
            return patterns
        digest = _stable_digest(f"{track_seed}:laser-program:{kind}:{context}:{ordinal}:{token}")
        offset = int.from_bytes(digest[:2], "big") % len(patterns)
        return patterns[offset:] + patterns[:offset]

    stage = _pattern_stage(kind)
    all_candidates = _pattern_candidates(
        family="laser",
        kind=kind,
        context=context,
        profile=profile,
    )
    release_stage = "breakdown" if stage in {"drop", "build"} else "intro"
    release_candidates = _dedupe(
        list(_LASER_PATTERN_POOLS.get(release_stage, _LASER_PATTERN_POOLS["intro"]))
        + ["fan", "thin_scan", "circle_trace"]
    )
    fill_hints = _TRANSITION_PATTERN_HINTS.get(context, {}).get("laser", [])
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
        sustain_patterns = [pattern for pattern in sustain_patterns if _LASER_PATTERN_GEOMETRY.get(pattern, "fan") in {"sky", "trace", "helix", "fan", "cone", "scan"}] or sustain_patterns
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
        "zone_policy": _laser_zone_policy(kind, context),
        "fill_trigger_every_bars": fill_cadence,
        "launch": launch_look,
        "sustain": sustain_looks,
        "fills": fill_looks,
        "release": release_look,
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


def _default_show_sections(
    markers: list[dict[str, Any]],
    duration_seconds: float,
    *,
    track_seed: str | None = None,
    selection_mode: str = "procedural",
    selection_variance: float = 0.0,
) -> list[dict[str, Any]]:
    if not markers:
        markers = _auto_markers_for_duration(duration_seconds)

    seed = track_seed or "unknown-track"
    selection_mode = _normalize_selection_mode(selection_mode)
    selection_variance = _normalize_selection_variance(selection_variance)
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
        section_patterns = _select_section_patterns(
            kind=kind,
            context=context,
            profile=profile,
            track_seed=seed,
            marker_name=str(marker["name"]),
            ordinal=ordinal,
            previous_patterns=previous_patterns,
            selection_mode=selection_mode,
            energy_scale=energy_scale,
            selection_variance=selection_variance,
        )
        laser_pattern = section_patterns["laser"]
        mover_pattern = section_patterns["mover"]
        wash_pattern = section_patterns["wash"]
        led_pattern = section_patterns["led"]
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
        )
        sections.append(
            {
                "generator_version": _SHOW_SECTION_GENERATOR_VERSION,
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
                "laser_program": _laser_program(
                    track_seed=seed,
                    base_pattern=laser_pattern,
                    kind=kind,
                    context=context,
                    ordinal=ordinal,
                    profile=profile,
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
    return sections


def _resolve_show_sections(
    persisted_show_plan: dict[str, Any] | None,
    markers: list[dict[str, Any]],
    duration_seconds: float,
    *,
    track_seed: str,
    selection_mode: str | None = None,
    selection_variance: float | None = None,
) -> list[dict[str, Any]]:
    """Load persisted sections when sane, otherwise rebuild a dynamic default plan."""
    resolved_selection_mode = _normalize_selection_mode(
        selection_mode
        if selection_mode is not None
        else (persisted_show_plan or {}).get("selection_mode")
    )
    resolved_selection_variance = _normalize_selection_variance(
        selection_variance
        if selection_variance is not None
        else (persisted_show_plan or {}).get("selection_variance")
    )
    generated_field_names = {
        "generator_version",
        "scene_id",
        "fixture_mode",
        "intensity_multiplier",
        "motion_multiplier",
        "strobe_level",
        "strobe_profile",
        "laser_pattern",
        "laser_variant",
        "laser_expression",
        "laser_program",
        "cue_recipe",
        "mover_pattern",
        "mover_variant",
        "wash_pattern",
        "wash_variant",
        "led_pattern",
        "led_variant",
        "laser_enabled",
        "movers_enabled",
        "washes_enabled",
        "leds_enabled",
    }

    def _laser_program_is_stale(program: Any) -> bool:
        if not isinstance(program, dict):
            return True
        if int(program.get("version", 0) or 0) != _LASER_PROGRAM_VERSION:
            return True
        sustain = program.get("sustain")
        fills = program.get("fills")
        launch = program.get("launch")
        release = program.get("release")
        if not isinstance(sustain, list) or not isinstance(fills, list):
            return True
        if len(sustain) != 2 or len(fills) != 2:
            return True
        if not isinstance(launch, dict) or not isinstance(release, dict):
            return True
        if str(launch.get("label", "")) != "Launch Hook":
            return True
        if str(release.get("label", "")) != "Release Hook":
            return True
        if [str(look.get("label", "")) for look in sustain] != ["Sustain A", "Sustain B"]:
            return True
        if [str(look.get("label", "")) for look in fills] != ["Fill A", "Fill B"]:
            return True
        return False

    def _generated_section_is_stale(section: dict[str, Any]) -> bool:
        if int(section.get("generator_version", 0) or 0) != _SHOW_SECTION_GENERATOR_VERSION:
            return True
        cue_recipe = section.get("cue_recipe")
        if not isinstance(cue_recipe, dict):
            return True
        if int(cue_recipe.get("version", 0) or 0) != _CUE_RECIPE_VERSION:
            return True
        return _laser_program_is_stale(section.get("laser_program"))

    fallback_sections_cache: list[dict[str, Any]] | None = None

    def _fallback_sections() -> list[dict[str, Any]]:
        nonlocal fallback_sections_cache
        if fallback_sections_cache is None:
            fallback_sections_cache = _default_show_sections(
                markers,
                duration_seconds,
                track_seed=track_seed,
                selection_mode=resolved_selection_mode,
                selection_variance=resolved_selection_variance,
            )
        return fallback_sections_cache

    if not persisted_show_plan or not isinstance(persisted_show_plan.get("show_sections"), list):
        return _fallback_sections()

    sections = [dict(section) for section in persisted_show_plan.get("show_sections", [])]
    if not sections:
        return _fallback_sections()

    sections.sort(key=lambda section: float(section.get("start_seconds", 0.0)))
    if (
        len(sections) == 1
        and str(sections[0].get("label", "")).startswith("Auto ")
    ):
        return _fallback_sections()
    if duration_seconds > 5 and max(float(section.get("end_seconds", 0.0)) for section in sections) <= 1.0:
        return _fallback_sections()

    selection_mode_mismatch = _normalize_selection_mode(
        persisted_show_plan.get("selection_mode")
    ) != resolved_selection_mode
    selection_variance_mismatch = _normalize_selection_variance(
        persisted_show_plan.get("selection_variance")
    ) != resolved_selection_variance

    normalized: list[dict[str, Any]] = []
    duration = max(0.001, float(duration_seconds))
    for index, section in enumerate(sections):
        normalized_section = dict(section)
        try:
            start = float(normalized_section.get("start_seconds", 0.0))
        except (TypeError, ValueError):
            return _fallback_sections()
        start = _clamp(start, 0.0, duration)
        if index + 1 < len(sections):
            try:
                next_start = float(sections[index + 1].get("start_seconds", duration))
            except (TypeError, ValueError):
                next_start = duration
        else:
            next_start = duration
        next_start = _clamp(next_start, start, duration)
        try:
            raw_end = float(normalized_section.get("end_seconds", next_start))
        except (TypeError, ValueError):
            raw_end = next_start
        end = _clamp(raw_end, start, duration)
        if end <= start:
            end = next_start if next_start > start else duration
        if end <= start:
            return _fallback_sections()
        normalized_section["start_seconds"] = round(start, 3)
        normalized_section["end_seconds"] = round(end, 3)
        if (
            selection_mode_mismatch
            or selection_variance_mismatch
            or _generated_section_is_stale(normalized_section)
        ) and index < len(_fallback_sections()):
            fallback_section = _fallback_sections()[index]
            for field_name in generated_field_names:
                normalized_section[field_name] = copy.deepcopy(fallback_section[field_name])
        normalized.append(normalized_section)

    if normalized[-1]["end_seconds"] < round(duration * 0.98, 3):
        normalized[-1]["end_seconds"] = round(duration, 3)

    return normalized


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
        clear_shared_control_plane_service,
        clear_shared_playback_context,
        set_shared_playback_context,
        set_shared_control_plane_service,
        PlaybackContext,
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
                    metadata_source="pro_dj_link",
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
        active_show_sections = _resolve_show_sections(
            persisted_show_plan,
            structure_markers,
            audio_node.duration_seconds,
            track_seed=track_key,
            selection_mode=selection_mode,
            selection_variance=selection_variance,
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
                selection_mode=mode,
                selection_variance=variance,
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


def main() -> None:
    """Entry point for the CLI."""
    cli(obj={})


if __name__ == "__main__":
    main()
