"""Curated phaser-bundle builder.

Per Task 2 Step 5 of the professional-lighting rollout plan. The phaser
family vocabulary is `pressure` for high-energy roles (build/drop and
their suffixed variants) and `breathing` for everything else.
"""

from __future__ import annotations

from typing import Any

from photonic_synesthesia.showplan.recipes import _is_high_energy_role


def build_phaser_bundle(*, section_role: str, lead_family: str) -> list[dict[str, Any]]:
    """Build a phaser bundle for a section.

    Returns a list-of-dicts so it slots directly into
    `cue_recipe["phasers"]`. Cycle-1 panel UF-12 / B5: callers should
    use `setdefault("phasers", build_phaser_bundle(...))` so operator
    edits are preserved across re-runs of `resolve_show_sections`.
    """
    family = "pressure" if _is_high_energy_role(section_role) else "breathing"
    return [
        {
            "family": family,
            "target": lead_family,
            "measure": 4,
            "speed_master": "groove",
            "width": 0.5,
            "transition": 0.5,
            "sync": True,
        }
    ]
