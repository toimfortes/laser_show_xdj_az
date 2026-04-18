"""Anti-template fingerprint + validation helpers for show-planning."""

from __future__ import annotations

import json
from hashlib import sha1
from typing import Any


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def show_fingerprint(show_sections: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute a stable fingerprint summarising a show plan's structural shape."""
    section_roles = [str(section.get("section_role") or "") for section in show_sections]
    lead_families = [str(section.get("lead_family") or "") for section in show_sections]
    transition_types = [
        str(section.get("transition_intent", {}).get("type") or "")
        for section in show_sections
    ]
    motif_ids = [
        motif_id
        for section in show_sections
        for motif_id in list(section.get("motif_ids") or [])
    ]
    palette_trajectory = [
        str(section.get("laser_expression", {}).get("color_mode") or section.get("wash_pattern") or "")
        for section in show_sections
    ]
    laser_families = [
        str(section.get("laser_expression", {}).get("geometry_family") or "")
        for section in show_sections
        if section.get("laser_enabled")
    ]
    strobe_total = round(sum(float(section.get("strobe_level") or 0.0) for section in show_sections), 3)
    density_curve = [
        round(
            _clamp(
                (
                    float(section.get("intensity_multiplier") or 0.0)
                    + float(section.get("motion_multiplier") or 0.0)
                    + float(section.get("strobe_level") or 0.0)
                )
                / 3.0,
                0.0,
                1.5,
            ),
            3,
        )
        for section in show_sections
    ]
    motif_counts: dict[str, int] = {}
    for motif_id in motif_ids:
        motif_counts[motif_id] = motif_counts.get(motif_id, 0) + 1
    laser_family_counts: dict[str, int] = {}
    for family in laser_families:
        laser_family_counts[family] = laser_family_counts.get(family, 0) + 1
    payload = {
        "version": 1,
        "section_roles": section_roles,
        "lead_families": lead_families,
        "transition_types": transition_types,
        "motif_ids": motif_ids,
        "motif_counts": motif_counts,
        "palette_trajectory": palette_trajectory,
        "laser_families": laser_families,
        "laser_family_counts": laser_family_counts,
        "strobe_total": strobe_total,
        "density_curve": density_curve,
    }
    payload["hash"] = sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    return payload


def sequence_similarity(left: list[str], right: list[str]) -> float:
    """Compute positional match ratio between two string sequences."""
    if not left and not right:
        return 0.0
    if not left or not right:
        return 1.0 if left == right else 0.0
    length = max(len(left), len(right), 1)
    matches = sum(
        1
        for index in range(length)
        if (left[index] if index < len(left) else "") == (right[index] if index < len(right) else "")
    )
    return round(matches / length, 3)


def set_similarity(current: dict[str, Any], previous: dict[str, Any]) -> float:
    """Score similarity between two show fingerprints as a weighted blend."""
    section_role_similarity = sequence_similarity(
        list(current.get("section_roles") or []),
        list(previous.get("section_roles") or []),
    )
    lead_similarity = sequence_similarity(
        list(current.get("lead_families") or []),
        list(previous.get("lead_families") or []),
    )
    transition_similarity = sequence_similarity(
        list(current.get("transition_types") or []),
        list(previous.get("transition_types") or []),
    )
    current_motif_sequence = list(current.get("motif_ids") or [])
    previous_motif_sequence = list(previous.get("motif_ids") or [])
    motif_sequence_similarity = sequence_similarity(current_motif_sequence, previous_motif_sequence)
    current_motif_counts = {str(key): int(value) for key, value in dict(current.get("motif_counts") or {}).items()}
    previous_motif_counts = {str(key): int(value) for key, value in dict(previous.get("motif_counts") or {}).items()}
    motif_keys = set(current_motif_counts) | set(previous_motif_counts)
    motif_similarity = (
        sum(min(current_motif_counts.get(key, 0), previous_motif_counts.get(key, 0)) for key in motif_keys)
        / max(1, sum(max(current_motif_counts.get(key, 0), previous_motif_counts.get(key, 0)) for key in motif_keys))
        if motif_keys
        else 0.0
    )
    current_laser_sequence = list(current.get("laser_families") or [])
    previous_laser_sequence = list(previous.get("laser_families") or [])
    laser_sequence_similarity = sequence_similarity(current_laser_sequence, previous_laser_sequence)
    current_laser_counts = {str(key): int(value) for key, value in dict(current.get("laser_family_counts") or {}).items()}
    previous_laser_counts = {str(key): int(value) for key, value in dict(previous.get("laser_family_counts") or {}).items()}
    laser_keys = set(current_laser_counts) | set(previous_laser_counts)
    laser_similarity = (
        sum(min(current_laser_counts.get(key, 0), previous_laser_counts.get(key, 0)) for key in laser_keys)
        / max(1, sum(max(current_laser_counts.get(key, 0), previous_laser_counts.get(key, 0)) for key in laser_keys))
        if laser_keys
        else 0.0
    )
    current_density = list(current.get("density_curve") or [])
    previous_density = list(previous.get("density_curve") or [])
    density_similarity = 1.0 - min(
        1.0,
        abs(sum(current_density) - sum(previous_density)) / max(0.001, sum(current_density) + sum(previous_density) + 0.001),
    )
    strobe_similarity = 1.0 - min(
        1.0,
        abs(float(current.get("strobe_total") or 0.0) - float(previous.get("strobe_total") or 0.0)),
    )
    return round(
        (
            section_role_similarity * 0.2
            + lead_similarity * 0.22
            + transition_similarity * 0.16
            + motif_similarity * 0.12
            + motif_sequence_similarity * 0.08
            + laser_similarity * 0.08
            + laser_sequence_similarity * 0.04
            + density_similarity * 0.05
            + strobe_similarity * 0.05
        ),
        3,
    )


def anti_template_validation(
    *,
    track_key: str,
    show_sections: list[dict[str, Any]],
    semantic_profile: dict[str, Any] | None,
    recent_catalog_entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Score a generated plan against recent catalog entries for repetition."""
    current_fingerprint = show_fingerprint(show_sections)
    recent_entries = list(recent_catalog_entries or [])
    nearest_tracks: list[dict[str, Any]] = []
    reused_motifs: set[str] = set()
    for payload in recent_entries:
        fingerprint = payload.get("show_fingerprint")
        if not isinstance(fingerprint, dict):
            fingerprint = show_fingerprint([dict(section) for section in payload.get("show_sections", [])])
        similarity = set_similarity(current_fingerprint, fingerprint)
        reused_motifs.update(set(current_fingerprint.get("motif_ids") or []) & set(fingerprint.get("motif_ids") or []))
        nearest_tracks.append(
            {
                "track_key": str(payload.get("track_key") or ""),
                "similarity": similarity,
                "fingerprint_hash": str(fingerprint.get("hash") or ""),
            }
        )
    nearest_tracks.sort(key=lambda item: float(item["similarity"]), reverse=True)
    mean_similarity = round(
        sum(float(item["similarity"]) for item in nearest_tracks) / len(nearest_tracks),
        3,
    ) if nearest_tracks else 0.0
    max_similarity = round(max((float(item["similarity"]) for item in nearest_tracks), default=0.0), 3)
    status = "pass"
    if max_similarity > 0.75 or mean_similarity > 0.7:
        status = "fail"
    elif max_similarity > 0.6 or mean_similarity > 0.55:
        status = "warn"
    genre_hints = list((semantic_profile or {}).get("genre_hints") or [])
    return {
        "version": 1,
        "status": status,
        "window": len(nearest_tracks),
        "mean_similarity": mean_similarity,
        "max_similarity": max_similarity,
        "nearest_tracks": nearest_tracks[:4],
        "reused_motifs": sorted(reused_motifs),
        "genre_hints": genre_hints,
        "show_fingerprint_hash": str(current_fingerprint.get("hash") or ""),
    }
