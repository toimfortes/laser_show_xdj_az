"""Operator-workspace bank builder.

Task 1 stub: returns an empty bank list. Task 4 Step 6 replaces with the
full implementation (scene/safety/tag bank construction). Signature MUST
match Task 4's so the Task-1 `snapshot()` call is wire-compatible without
further work.

Cycle-1 panel UF-14 fix.
"""

from __future__ import annotations

from typing import Any


def build_operator_workspace_banks(
    *,
    sections: list[dict[str, Any]],
    available_tags: list[str],
    safety_modes: tuple[str, ...],
) -> dict[str, Any]:
    """Empty bank stub. Task 4 Step 6 produces the real bank list."""
    return {"banks": []}
