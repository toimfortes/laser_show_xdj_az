"""Operator-workspace bank builder.

Per Task 4 Step 6 of the professional-lighting rollout plan. Returns the
workspace bank STRUCTURE — scene buttons (one per section), safety-mode
buttons (the `SAFETY_MODES` tuple), tag buttons (deduped section tags).
The active scene id is NOT part of the cached bank structure; it lives
in the per-call live overlay in `PlaybackContext.snapshot()` (cycle-1
panel UF-7).

Cycle-2 panel NC-9 + cycle-3 panel 3C-H1: all `safety_modes` consumers
(this builder, ilda_output's _ZONE_POLICY_RULES validation, recipe
bundles) must import the single `SAFETY_MODES` tuple from
`photonic_synesthesia.showplan.types`.
"""

from __future__ import annotations

from typing import Any


def build_operator_workspace_banks(
    *,
    sections: list[dict[str, Any]],
    available_tags: list[str],
    safety_modes: tuple[str, ...],
) -> dict[str, Any]:
    """Build the bank structure for the operator workspace UI.

    Returns a dict with one `banks` key whose value is a list of three
    bank dicts (`scene`, `safety`, `tags`). Each bank has `id` and
    `buttons`; each button has `id` (machine-stable, prefixed) and
    `label` (human-readable).
    """
    return {
        "banks": [
            {
                "id": "scene",
                "buttons": [
                    {
                        "id": f"scene:{section.get('id', '')}",
                        "label": str(section.get("label") or section.get("id") or ""),
                    }
                    for section in sections
                ],
            },
            {
                "id": "safety",
                "buttons": [
                    {"id": f"safety:{mode}", "label": mode} for mode in safety_modes
                ],
            },
            {
                "id": "tags",
                "buttons": [{"id": f"tag:{tag}", "label": tag} for tag in available_tags],
            },
        ]
    }
