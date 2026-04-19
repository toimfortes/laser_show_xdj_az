"""Authored timeline-flag derivation.

Task 1 stub: returns an empty list. Task 2 Step 6 replaces with the full
implementation that emits `phrase_head` + transition-typed flags per section.
The Task-1 stub keeps `runtime_context.py`'s `_replace_show_sections_locked`
import path resolvable so the architecture slice can land independently.

Cycle-5 panel Codex-HIGH-2 fix: the cycle-4 plan imported
`derive_timeline_flags` from this module without creating it; cycle 5
adds this stub.
"""

from __future__ import annotations

from typing import Any

from photonic_synesthesia.showplan.types import TimelineFlag


def derive_timeline_flags(show_sections: list[dict[str, Any]]) -> list[TimelineFlag]:
    """Empty stub. Task 2 Step 6 produces the real flag list."""
    return []
