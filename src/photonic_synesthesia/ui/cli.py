"""
Command-Line Interface for Photonic Synesthesia.

Provides commands for running the system, testing fixtures,
and calibrating sensors.
"""

from __future__ import annotations

import copy
import json
import logging
import os
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
from photonic_synesthesia.showplan import (
    build_show_catalog_entry as _showplan_build_show_catalog_entry,
)
from photonic_synesthesia.showplan import (
    resolve_show_sections as _showplan_resolve_show_sections,
)
from photonic_synesthesia.showplan._patterns import (
    ollama_section_selection as _ollama_section_selection,
)
from photonic_synesthesia.showplan._patterns import (
    pattern_candidates as _pattern_candidates,
)
from photonic_synesthesia.showplan._patterns import (
    select_pattern as _select_pattern,
)
from photonic_synesthesia.showplan.creative_profiles import (
    CREATIVE_PROFILES as _CREATIVE_PROFILES,
)
from photonic_synesthesia.showplan.sections import (
    default_show_sections as _showplan_default_show_sections,
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
    clamp as _clamp,
)
from photonic_synesthesia.showplan.types import (
    normalize_venue_mode as _normalize_venue_mode,
)
from photonic_synesthesia.showplan.validation import (
    anti_template_validation as _showplan_anti_template_validation,
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
            # v2-added fields surfaced to bind_track_metadata (cycle-1 panel
            # UF-1, UF-3; cycle-3 panel NC-7). Helper installs them via the
            # _persisted_timeline_flags_hint + staged_look paths.
            "timeline_flags": copy.deepcopy((persisted_show_plan or {}).get("timeline_flags", []) or []),
            "staged_look": copy.deepcopy((persisted_show_plan or {}).get("staged_look")),
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
    # Thin back-compat wrapper: showplan.default_show_sections owns the
    # planner behaviour outright now; this shim exists because a few tests
    # still import it as cli._default_show_sections. New code should import
    # from photonic_synesthesia.showplan directly.
    return _showplan_default_show_sections(
        markers,
        duration_seconds,
        track_seed=track_seed,
        semantic_profile=semantic_profile,
        selection_mode=selection_mode,
        selection_variance=selection_variance,
        venue_mode=venue_mode,
        metadata_confidence=metadata_confidence,
    )


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
                fixtures_dir=settings.fixtures_dir,
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
                    # v2-added persisted fields (cycle-1 panel UF-1 + UF-3).
                    timeline_flags=copy.deepcopy((persisted_show_plan or {}).get("timeline_flags", []) or []),
                    staged_look=copy.deepcopy((persisted_show_plan or {}).get("staged_look")),
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
                fixtures_dir=settings.fixtures_dir,
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
    # showplan.catalog owns the planner behaviour and calls its sibling
    # showplan modules directly; the CLI injects only true external
    # dependencies — catalog-directory I/O and ollama provenance lookup.
    return _showplan_build_show_catalog_entry(
        **kwargs,
        recent_catalog_entries_fn=_recent_catalog_entries,
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
        laser_program_version=_LASER_PROGRAM_VERSION,
        show_section_generator_version=_SHOW_SECTION_GENERATOR_VERSION,
        cue_recipe_version=_CUE_RECIPE_VERSION,
    )


def main() -> None:
    """Entry point for the CLI."""
    cli(obj={})


if __name__ == "__main__":
    main()
