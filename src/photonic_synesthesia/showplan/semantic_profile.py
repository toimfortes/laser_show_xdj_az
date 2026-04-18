"""Semantic profile helpers for show-planning."""

from __future__ import annotations

import copy
from typing import Any

from photonic_synesthesia.showplan.types import (
    SEMANTIC_PROFILE_VERSION,
    clamp as _clamp,
    safe_confidence_value,
)


def auto_markers_for_duration(duration_seconds: float) -> list[dict[str, Any]]:
    """Generate phrase markers when no Rekordbox structure is available."""
    duration = max(1.0, float(duration_seconds))
    if duration <= 75:
        target_count = 4
    else:
        target_count = int(max(5, min(10, round(duration / 28.0))))

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


def build_semantic_profile(
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
        else auto_markers_for_duration(duration_seconds)
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
        "version": SEMANTIC_PROFILE_VERSION,
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


def metadata_confidence(
    *,
    structure_markers: list[dict[str, Any]],
    metadata_source: str,
    rekordbox_track_id: str = "",
    rekordbox_average_bpm: float | None = None,
    web_enrichment: dict[str, Any] | None = None,
    matched_rekordbox_track: bool = False,
) -> dict[str, Any]:
    normalized_source = str(metadata_source or "manual").strip().lower().replace("-", "_") or "manual"
    markers_present = bool(structure_markers)
    web_confidence = copy.deepcopy((web_enrichment or {}).get("confidence", {}))
    web_score = safe_confidence_value(
        web_confidence.get("overall", web_confidence.get("consensus", 0.45)),
        default=0.45 if web_enrichment else 0.0,
    )

    track_match_confidence = 0.35
    phrase_confidence = 0.25
    beatgrid_confidence = 0.3
    transport_confidence = 0.2

    if rekordbox_track_id or matched_rekordbox_track:
        track_match_confidence = 0.96 if matched_rekordbox_track else 0.88
        beatgrid_confidence = 0.94
    elif markers_present:
        track_match_confidence = 0.72
        beatgrid_confidence = 0.62

    if markers_present:
        phrase_confidence = 0.9 if matched_rekordbox_track or rekordbox_track_id else 0.7

    if normalized_source == "pro_dj_link":
        transport_confidence = 0.93 if matched_rekordbox_track or rekordbox_track_id else 0.74
    elif normalized_source == "file_playback":
        transport_confidence = 0.58 if markers_present else 0.42
    elif normalized_source in {"rekordbox_export", "catalog"}:
        transport_confidence = 0.65 if markers_present else 0.38

    if rekordbox_average_bpm is not None:
        beatgrid_confidence = max(beatgrid_confidence, 0.86)

    confidence_tier = "degraded"
    if transport_confidence >= 0.85 and phrase_confidence >= 0.8:
        confidence_tier = "strict"
    elif beatgrid_confidence >= 0.7:
        confidence_tier = "beat_safe"

    return {
        "track_match_confidence": round(track_match_confidence, 3),
        "phrase_confidence": round(phrase_confidence, 3),
        "beatgrid_confidence": round(beatgrid_confidence, 3),
        "web_enrichment_confidence": web_score,
        "transport_confidence": round(transport_confidence, 3),
        "confidence_tier": confidence_tier,
        "source_precedence": [
            "rekordbox_edited_markers",
            "rekordbox_track_match",
            "beatgrid_transport",
            "audio_fallback",
            "web_enrichment",
        ],
        "sources": {
            "rekordbox_markers": markers_present,
            "rekordbox_track_match": bool(rekordbox_track_id or matched_rekordbox_track),
            "live_transport": normalized_source == "pro_dj_link",
            "web_enrichment": bool(web_enrichment),
        },
    }
