"""Pure helpers for the operator preview/commit staging lane.

Per Task 4 Step 6. `stage_look` builds the preview-only `staged_look`
dict; `commit_staged_look` flips its `committed` flag to True. These
are pure functions (no I/O, no shared state) so they're testable in
isolation; the locked write paths live on `PlaybackContext`
(`set_staged_look` + `commit_staged_look` methods).

Cycle-1 panel UF-11: preview-only semantics — `staged_look` surfaces
in `playback_snapshot` for UI rendering and nowhere else; the runtime
graph reads `show_sections` ONLY. Commit is the single explicit
moment where operator intent overrides authored defaults; after commit
the merged section becomes the new authored state.
"""

from __future__ import annotations

import copy
from typing import Any


def stage_look(
    *,
    section_id: str,
    cue_recipe: dict[str, Any],
    laser_program: dict[str, Any],
) -> dict[str, Any]:
    """Build a preview-only staged_look dict."""
    return {
        "id": f"staged:{section_id}",
        "source": "operator",
        "section_id": section_id,
        "cue_recipe": copy.deepcopy(cue_recipe),
        "laser_program": copy.deepcopy(laser_program),
        "committed": False,
    }


def commit_staged_look(staged_look: dict[str, Any]) -> dict[str, Any]:
    """Flip a staged_look's `committed` flag. Returns a new dict."""
    committed = copy.deepcopy(staged_look)
    committed["committed"] = True
    return committed
