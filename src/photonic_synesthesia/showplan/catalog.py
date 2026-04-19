"""Show catalog entry builder for the showplan facade.

Assembles the per-track catalog entry. Most of the planner logic lives
in sibling showplan modules and is called directly — only true external
dependencies (catalog dir I/O for the cross-track repetition check,
ollama config for provenance) stay injectable.

The review panel on 2026-04-19 flagged an earlier version of this
module for taking thirteen behavior callbacks and hard-failing when any
were missing — "architectural theater" that left ui/cli.py as the real
planner. That indirection is gone; the callbacks now come in only where
there's a real ownership boundary (I/O, config).
"""

from __future__ import annotations

import copy
import socket
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from photonic_synesthesia.showplan.model_payloads import (
    build_catalog_model_payload as _build_catalog_model_payload,
)
from photonic_synesthesia.showplan.motifs import (
    decorate_show_sections_with_motifs as _decorate_show_sections_with_motifs,
)
from photonic_synesthesia.showplan.motifs import (
    motif_registry as _motif_registry,
)
from photonic_synesthesia.showplan.preview import (
    preview_artifacts as _preview_artifacts,
)
from photonic_synesthesia.showplan.scoring import (
    scorer_bundle as _scorer_bundle,
)
from photonic_synesthesia.showplan.sections import (
    default_show_sections as _default_show_sections,
)
from photonic_synesthesia.showplan.semantic_profile import (
    build_semantic_profile as _build_semantic_profile,
)
from photonic_synesthesia.showplan.semantic_profile import (
    metadata_confidence as _metadata_confidence,
)
from photonic_synesthesia.showplan.types import (
    CATALOG_VERSION as _CATALOG_VERSION,
)
from photonic_synesthesia.showplan.types import (
    LASER_PROGRAM_VERSION as _LASER_PROGRAM_VERSION,
)
from photonic_synesthesia.showplan.types import (
    SHOW_SECTION_GENERATOR_VERSION as _SHOW_SECTION_GENERATOR_VERSION,
)
from photonic_synesthesia.showplan.types import (
    normalize_selection_mode as _normalize_selection_mode,
)
from photonic_synesthesia.showplan.types import (
    normalize_selection_variance as _normalize_selection_variance,
)
from photonic_synesthesia.showplan.types import (
    normalize_venue_mode as _normalize_venue_mode,
)
from photonic_synesthesia.showplan.validation import (
    anti_template_validation as _anti_template_validation,
)
from photonic_synesthesia.showplan.validation import (
    show_fingerprint as _show_fingerprint,
)


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
    recent_catalog_entries_fn: Callable[[str], list[dict[str, Any]]] | None = None,
    ollama_model_name_fn: Callable[[], str] | None = None,
    ollama_num_gpu_option_fn: Callable[[], int | None] | None = None,
    catalog_version: int = _CATALOG_VERSION,
    show_section_generator_version: int = _SHOW_SECTION_GENERATOR_VERSION,
    laser_program_version: int = _LASER_PROGRAM_VERSION,
) -> dict[str, Any]:
    # External-dependency callbacks: default to "empty" so showplan remains
    # callable without the CLI present. Production callers (ui/cli.py) inject
    # real catalog-directory I/O and ollama-config lookups; test and demo
    # callers can omit.
    _recent_catalog_entries = recent_catalog_entries_fn or (lambda _track_key: [])
    _ollama_model_name = ollama_model_name_fn or (lambda: "")
    _ollama_num_gpu_option = ollama_num_gpu_option_fn or (lambda: None)

    selection_mode = _normalize_selection_mode(selection_mode)
    selection_variance = _normalize_selection_variance(selection_variance)
    venue_mode = _normalize_venue_mode(venue_mode)
    metadata_confidence = _metadata_confidence(
        structure_markers=structure_markers,
        metadata_source="rekordbox_export" if rekordbox_source is not None else "catalog",
        rekordbox_track_id=rekordbox_track_id,
        rekordbox_average_bpm=rekordbox_average_bpm,
        web_enrichment=web_enrichment,
        matched_rekordbox_track=bool(rekordbox_track_id),
    )
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
        semantic_profile=semantic_profile,
        selection_mode=selection_mode,
        selection_variance=selection_variance,
        venue_mode=venue_mode,
        metadata_confidence=metadata_confidence,
    )
    show_sections = _decorate_show_sections_with_motifs(show_sections)
    recent_catalog_entries = _recent_catalog_entries(track_key)
    show_fingerprint_value = _show_fingerprint(show_sections)
    anti_template_validation_value = _anti_template_validation(
        track_key=track_key,
        show_sections=show_sections,
        semantic_profile=semantic_profile,
        recent_catalog_entries=recent_catalog_entries,
    )
    motif_registry_value = _motif_registry(
        track_key=track_key,
        show_sections=show_sections,
        recent_catalog_entries=recent_catalog_entries,
    )
    scorer_bundle_value = _scorer_bundle(
        show_sections=show_sections,
        semantic_profile=semantic_profile,
        anti_template_validation=anti_template_validation_value,
        venue_mode=venue_mode,
    )
    preview_artifacts_value = _preview_artifacts(track_key, show_sections)
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
                semantic_profile=semantic_profile,
                selection_mode=selection_mode,
                selection_variance=variance,
                venue_mode=venue_mode,
                metadata_confidence=metadata_confidence,
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
        venue_mode=venue_mode,
        rekordbox_track_id=rekordbox_track_id,
        rekordbox_average_bpm=rekordbox_average_bpm,
        semantic_profile=semantic_profile,
        metadata_confidence=metadata_confidence,
        web_enrichment=web_enrichment,
        motif_registry=motif_registry_value,
        show_fingerprint=show_fingerprint_value,
        anti_template_validation=anti_template_validation_value,
        scorer_bundle=scorer_bundle_value,
        preview_artifacts=preview_artifacts_value,
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
        "motif_registry": motif_registry_value,
        "show_fingerprint": show_fingerprint_value,
        "anti_template_validation": anti_template_validation_value,
        "scorer_bundle": scorer_bundle_value,
        "preview_artifacts": preview_artifacts_value,
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
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "planner_version": show_section_generator_version,
            "laser_program_version": laser_program_version,
            "selection_mode": selection_mode,
            "selection_variance": selection_variance,
            "venue_mode": venue_mode,
            "ollama_model": _ollama_model_name() if selection_mode == "local_ollama_cpu" else "",
            "ollama_num_gpu": _ollama_num_gpu_option() if selection_mode == "local_ollama_cpu" else "",
            "generator_host": socket.gethostname(),
            "web_enrichment_version": int((web_enrichment or {}).get("version", 0) or 0),
        },
    }
