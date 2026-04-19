"""Preview-artifact plan for showplan catalog entries.

Returns a deterministic list of preview artifact path hints (per-section
stills, clips, long exposures for high-intensity sections). The planner
does not render anything — it publishes the plan so a downstream tool
can materialize the artifacts.

Previously lived in ``ui/cli.py`` and was injected via
``preview_artifacts_fn``; moved here so showplan calls directly.
"""

from __future__ import annotations

from hashlib import sha1
from typing import Any


def preview_artifacts(track_key: str, show_sections: list[dict[str, Any]]) -> dict[str, Any]:
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
