"""Show catalog entry builder for the showplan facade."""

from __future__ import annotations

import copy
import socket
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from photonic_synesthesia.showplan.types import (
    CATALOG_VERSION as _CATALOG_VERSION,
)
from photonic_synesthesia.showplan.types import (
    LASER_PROGRAM_VERSION as _LASER_PROGRAM_VERSION,
)
from photonic_synesthesia.showplan.types import (
    SHOW_SECTION_GENERATOR_VERSION as _SHOW_SECTION_GENERATOR_VERSION,
)


def _identity_selection_mode(selection_mode: str | None) -> str:
    if selection_mode is None:
        return "procedural"
    return str(selection_mode)


def _identity_selection_variance(value: Any | None) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _identity_venue_mode(value: str | None) -> str:
    if value is None:
        return "small_room_50_100"
    return str(value)


def build_show_catalog_entry(
    *,
    audio_file: Path,
    duration_seconds: float,
    structure_markers: list[dict[str, Any]],
    track_key: str,
    track_title: str,
    track_artist: str,
    selection_mode: str,
    selection_variance: float,
    venue_mode: str,
    rekordbox_source: Path | None,
    rekordbox_track_id: str = "",
    rekordbox_average_bpm: float | None = None,
    web_enrichment: dict[str, Any] | None = None,
    normalize_selection_mode: Callable[[str | None], str] | None = None,
    normalize_selection_variance: Callable[[Any | None], float] | None = None,
    normalize_venue_mode: Callable[[str | None], str] | None = None,
    metadata_confidence_fn: Callable[..., dict[str, Any]] | None = None,
    build_semantic_profile_fn: Callable[..., dict[str, Any]] | None = None,
    default_show_sections_fn: Callable[..., list[dict[str, Any]]] | None = None,
    decorate_show_sections_with_motifs_fn: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
    recent_catalog_entries_fn: Callable[[str], list[dict[str, Any]]] | None = None,
    show_fingerprint_fn: Callable[[list[dict[str, Any]]], dict[str, Any]] | None = None,
    anti_template_validation_fn: Callable[..., dict[str, Any]] | None = None,
    motif_registry_fn: Callable[..., dict[str, Any]] | None = None,
    scorer_bundle_fn: Callable[..., dict[str, Any]] | None = None,
    preview_artifacts_fn: Callable[..., dict[str, Any]] | None = None,
    build_catalog_model_payload_fn: Callable[..., dict[str, Any]] | None = None,
    ollama_model_name_fn: Callable[[], str] | None = None,
    ollama_num_gpu_option_fn: Callable[[], int | None] | None = None,
    catalog_version: int = _CATALOG_VERSION,
    show_section_generator_version: int = _SHOW_SECTION_GENERATOR_VERSION,
    laser_program_version: int = _LASER_PROGRAM_VERSION,
) -> dict[str, Any]:
    _normalize_selection_mode = normalize_selection_mode or _identity_selection_mode
    _normalize_selection_variance = normalize_selection_variance or _identity_selection_variance
    _normalize_venue_mode = normalize_venue_mode or _identity_venue_mode

    if metadata_confidence_fn is None:
        raise RuntimeError("build_show_catalog_entry requires metadata_confidence_fn")
    if build_semantic_profile_fn is None:
        raise RuntimeError("build_show_catalog_entry requires build_semantic_profile_fn")
    if default_show_sections_fn is None:
        raise RuntimeError("build_show_catalog_entry requires default_show_sections_fn")
    if decorate_show_sections_with_motifs_fn is None:
        raise RuntimeError("build_show_catalog_entry requires decorate_show_sections_with_motifs_fn")
    if recent_catalog_entries_fn is None:
        raise RuntimeError("build_show_catalog_entry requires recent_catalog_entries_fn")
    if show_fingerprint_fn is None:
        raise RuntimeError("build_show_catalog_entry requires show_fingerprint_fn")
    if anti_template_validation_fn is None:
        raise RuntimeError("build_show_catalog_entry requires anti_template_validation_fn")
    if motif_registry_fn is None:
        raise RuntimeError("build_show_catalog_entry requires motif_registry_fn")
    if scorer_bundle_fn is None:
        raise RuntimeError("build_show_catalog_entry requires scorer_bundle_fn")
    if preview_artifacts_fn is None:
        raise RuntimeError("build_show_catalog_entry requires preview_artifacts_fn")
    if build_catalog_model_payload_fn is None:
        raise RuntimeError("build_show_catalog_entry requires build_catalog_model_payload_fn")
    if ollama_model_name_fn is None:
        raise RuntimeError("build_show_catalog_entry requires ollama_model_name_fn")
    if ollama_num_gpu_option_fn is None:
        raise RuntimeError("build_show_catalog_entry requires ollama_num_gpu_option_fn")

    selection_mode = _normalize_selection_mode(selection_mode)
    selection_variance = _normalize_selection_variance(selection_variance)
    venue_mode = _normalize_venue_mode(venue_mode)
    metadata_confidence = metadata_confidence_fn(
        structure_markers=structure_markers,
        metadata_source="rekordbox_export" if rekordbox_source is not None else "catalog",
        rekordbox_track_id=rekordbox_track_id,
        rekordbox_average_bpm=rekordbox_average_bpm,
        web_enrichment=web_enrichment,
        matched_rekordbox_track=bool(rekordbox_track_id),
    )
    semantic_profile = build_semantic_profile_fn(
        track_title=track_title,
        track_artist=track_artist,
        duration_seconds=duration_seconds,
        structure_markers=structure_markers,
        rekordbox_average_bpm=rekordbox_average_bpm,
        web_enrichment=web_enrichment,
    )
    show_sections = default_show_sections_fn(
        structure_markers,
        duration_seconds,
        track_seed=track_key,
        semantic_profile=semantic_profile,
        selection_mode=selection_mode,
        selection_variance=selection_variance,
        venue_mode=venue_mode,
        metadata_confidence=metadata_confidence,
    )
    show_sections = decorate_show_sections_with_motifs_fn(show_sections)
    recent_catalog_entries = recent_catalog_entries_fn(track_key)
    show_fingerprint = show_fingerprint_fn(show_sections)
    anti_template_validation = anti_template_validation_fn(
        track_key=track_key,
        show_sections=show_sections,
        semantic_profile=semantic_profile,
        recent_catalog_entries=recent_catalog_entries,
    )
    motif_registry = motif_registry_fn(
        track_key=track_key,
        show_sections=show_sections,
        recent_catalog_entries=recent_catalog_entries,
    )
    scorer_bundle = scorer_bundle_fn(
        show_sections=show_sections,
        semantic_profile=semantic_profile,
        anti_template_validation=anti_template_validation,
        venue_mode=venue_mode,
    )
    preview_artifacts = preview_artifacts_fn(track_key, show_sections)
    alternate_variances = {
        "tight": 0.0,
        "balanced": 0.35,
        "wild": 0.75,
    }
    alternates = {
        label: {
            "selection_mode": selection_mode,
            "selection_variance": variance,
            "show_sections": default_show_sections_fn(
                structure_markers,
                duration_seconds,
                track_seed=track_key,
                semantic_profile=semantic_profile,
                selection_mode=selection_mode,
                selection_variance=variance,
                venue_mode=venue_mode,
                metadata_confidence=metadata_confidence,
            ),
        }
        for label, variance in alternate_variances.items()
    }
    model_payload = build_catalog_model_payload_fn(
        track_key=track_key,
        track_title=track_title,
        track_artist=track_artist,
        duration_seconds=duration_seconds,
        structure_markers=structure_markers,
        show_sections=show_sections,
        selection_mode=selection_mode,
        selection_variance=selection_variance,
        venue_mode=venue_mode,
        rekordbox_track_id=rekordbox_track_id,
        rekordbox_average_bpm=rekordbox_average_bpm,
        semantic_profile=semantic_profile,
        metadata_confidence=metadata_confidence,
        web_enrichment=web_enrichment,
        motif_registry=motif_registry,
        show_fingerprint=show_fingerprint,
        anti_template_validation=anti_template_validation,
        scorer_bundle=scorer_bundle,
        preview_artifacts=preview_artifacts,
    )
    return {
        "catalog_version": catalog_version,
        "track_key": track_key,
        "track_title": track_title,
        "track_artist": track_artist,
        "file_name": audio_file.name,
        "file_path": str(audio_file),
        "duration_seconds": round(float(duration_seconds), 3),
        "structure_markers": [dict(marker) for marker in structure_markers],
        "selection_mode": selection_mode,
        "selection_variance": selection_variance,
        "venue_mode": venue_mode,
        "semantic_profile": semantic_profile,
        "metadata_confidence": metadata_confidence,
        "motif_registry": motif_registry,
        "show_fingerprint": show_fingerprint,
        "anti_template_validation": anti_template_validation,
        "scorer_bundle": scorer_bundle,
        "preview_artifacts": preview_artifacts,
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
            "planner_version": show_section_generator_version,
            "laser_program_version": laser_program_version,
            "selection_mode": selection_mode,
            "selection_variance": selection_variance,
            "venue_mode": venue_mode,
            "ollama_model": ollama_model_name_fn() if selection_mode == "local_ollama_cpu" else "",
            "ollama_num_gpu": ollama_num_gpu_option_fn() if selection_mode == "local_ollama_cpu" else "",
            "generator_host": socket.gethostname(),
            "web_enrichment_version": int((web_enrichment or {}).get("version", 0) or 0),
        },
    }
