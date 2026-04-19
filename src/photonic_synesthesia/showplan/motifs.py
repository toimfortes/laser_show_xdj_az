"""Motif extraction + registry for showplan sections.

A "motif" is a compact identifier for a section's creative choices
(role, lead family, per-family pattern, laser geometry, transition
type). The catalog uses motif IDs to detect self-repetition within a
track and cross-track reuse against the recent catalog window.

Previously lived in ``ui/cli.py`` and was injected into showplan via
``decorate_show_sections_with_motifs_fn`` / ``motif_registry_fn``
callbacks. Moved here so showplan can call directly and the facade
boundary stays clean.
"""

from __future__ import annotations

from typing import Any


def section_motif_ids(section: dict[str, Any]) -> list[str]:
    """Return the canonical motif ID list for a single section."""
    section_role = str(section.get("section_role") or section.get("kind") or "section")
    lead_family = str(section.get("lead_family") or "none")
    motifs = [f"role:{section_role}", f"lead:{section_role}:{lead_family}"]
    for family in ("laser", "mover", "wash", "led"):
        if family == "laser":
            enabled_flag = bool(section.get("laser_enabled", False))
        elif family == "mover":
            enabled_flag = bool(section.get("movers_enabled", False))
        elif family == "wash":
            enabled_flag = bool(section.get("washes_enabled", False))
        else:
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


def decorate_show_sections_with_motifs(
    show_sections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """In-place: add motif_ids/motif_primary to each section and its cue recipe.

    Also counts per-motif occurrences across the section list and records
    a motif_reuse_count on each section's cue_recipe — downstream consumers
    use this to weight repetition penalties.
    """
    motif_counts: dict[str, int] = {}
    for section in show_sections:
        motif_ids = section_motif_ids(section)
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


def motif_registry(
    *,
    track_key: str,
    show_sections: list[dict[str, Any]],
    recent_catalog_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare current-track motifs against the recent catalog window.

    ``recent_catalog_entries`` must be provided by the caller — showplan
    does not own catalog I/O. Pass the result of
    ``list_show_catalog_paths`` + parsing. If no recent entries are
    available, pass an empty list.
    """
    recent_entries = list(recent_catalog_entries)
    recent_track_keys = [str(payload.get("track_key") or "") for payload in recent_entries[:4]]
    current_motifs = sorted(
        {motif for section in show_sections for motif in list(section.get("motif_ids") or [])}
    )
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
