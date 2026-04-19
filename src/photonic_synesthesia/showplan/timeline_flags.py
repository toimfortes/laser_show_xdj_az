"""Authored timeline-flag derivation.

Task 2 Step 6 full implementation. Each section emits at minimum a
`phrase_head` flag at its start. Sections with a non-empty
`transition_intent.type` emit a second flag keyed on that type so
TriggerRouterNode can route bloom/handoff/suckout/etc. transitions
without re-scanning the section list.

Cycle-2 panel NC-3: `_compute_flags_hash` in `runtime_context.py` keys
on `(id, at_seconds)`; an order-shuffle of the persisted list does NOT
trip a trigger-ledger reset. The hash material excludes payload by
design so a payload-only edit doesn't fire-clear the ledger either.
"""

from __future__ import annotations

from typing import Any

from photonic_synesthesia.showplan.types import TimelineFlag


def derive_timeline_flags(show_sections: list[dict[str, Any]]) -> list[TimelineFlag]:
    """Emit a deterministic timeline-flag list from authored sections."""
    flags: list[TimelineFlag] = []
    for section in show_sections:
        section_id = str(section.get("id") or "")
        if not section_id:
            continue
        at_seconds = float(section.get("start_seconds", 0.0))
        flags.append(
            {
                "id": f"{section_id}:phrase_head",
                "kind": "phrase_head",
                "at_seconds": at_seconds,
                "payload": {"section_id": section_id},
            }
        )
        transition = section.get("transition_intent")
        transition_type = ""
        if isinstance(transition, dict):
            transition_type = str(transition.get("type") or "")
        if transition_type:
            flags.append(
                {
                    "id": f"{section_id}:{transition_type}",
                    "kind": transition_type,
                    "at_seconds": at_seconds,
                    "payload": {"section_id": section_id},
                }
            )
    return flags
