"""Deterministic recipe-bundle builder for authored cue recipes.

Per Task 2 Step 5 of the professional-lighting rollout plan. Produces the
recipe-line + next-position structure that `cue_recipe` payloads carry.
Cycle-1 panel UF-25 acceptance: the role-prefix matcher handles both
coarse (`build`, `drop`) and suffixed (`build_1`, `drop_variation`) forms
so high-energy variants hit the intended high-energy path.
"""

from __future__ import annotations

from typing import Any


def _is_high_energy_role(section_role: str) -> bool:
    """Match coarse and suffixed high-energy section roles."""
    role = (section_role or "").strip().lower()
    return role.startswith("build") or role.startswith("drop")


def build_recipe_bundle(
    *,
    section_role: str,
    lead_family: str,
    target_mode: str,
    cue_family_id: str,
) -> dict[str, Any]:
    """Build a deterministic recipe bundle for a section.

    Returns a dict suitable for use as the missing-keys default in a
    `cue_recipe` setdefault merge (cycle-1 panel UF-12: preserve
    operator-edited fields; only fill gaps).
    """
    high_energy = _is_high_energy_role(section_role)
    return {
        "cue_family_id": cue_family_id,
        "next_positions": ["fan_open"] if high_energy else [f"{lead_family}:home"],
        "recipe_lines": [
            {
                "selection": f"{lead_family}:{section_role}",
                "preset": f"{section_role}:{target_mode}",
                "filter": "default",
                "matricks": "symmetry",
                "fade": 0.25,
                "delay": 0.0,
                "speed_master": "groove",
                "timing_master": "phrase",
                "phase": 0.0,
            }
        ],
    }
