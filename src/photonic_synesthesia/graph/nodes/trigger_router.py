"""Trigger router runtime node.

Reads authored timeline_flags from `state["playback_snapshot"]` and emits
due flag-fire events into `state["trigger_events"]`. Per Task 3 of the
professional-lighting rollout plan.

Cycle-1 panel UF-9 + cycle-2 panel NC-3: ledger reset keys on the
authored-state revision (`timeline_flag_revision` = `_flags_hash`),
NOT `transport_revision`. Routine playhead progression preserves the
fire-once ledger.

Cycle-3 panel 3C-N1 + cycle-4 panel NC-4: ledger reset is split:
- "authored change at non-zero playhead" → pre-populate `_fired_ids`
  with past flags so only newly-crossed flags fire (no thundering herd).
- "backward seek" → clear ledger fully so past flags re-fire on replay.
- "first tick ever" (`_last_timeline_flag_revision = -1`) → fall through
  to ordinary due-detection so canonical `at_seconds=0.0` flags fire.
"""

from __future__ import annotations

from typing import Any


class TriggerRouterNode:
    """Emit timeline-flag fire events with fire-once-per-ledger semantics."""

    def __init__(self) -> None:
        self._fired_ids: set[str] = set()
        self._last_playhead = 0.0
        self._last_timeline_flag_revision = -1  # sentinel for "no prior tick"

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        snapshot = dict(state.get("playback_snapshot") or {})
        playhead = float(snapshot.get("playhead_seconds", 0.0))
        timeline_flag_revision = int(snapshot.get("timeline_flag_revision", 0))
        flags = list(snapshot.get("timeline_flags", []))

        revision_changed = timeline_flag_revision != self._last_timeline_flag_revision
        rewound = playhead < self._last_playhead
        is_initial_tick = self._last_timeline_flag_revision < 0

        if revision_changed and not rewound and not is_initial_tick:
            # Authored state changed during forward playback. Pre-populate
            # past flags so only newly-crossed flags fire (cycle-3 panel
            # 3C-N1 / cycle-2 panel NC-4 thundering-herd fix).
            self._fired_ids = {
                str(flag["id"]) for flag in flags
                if float(flag.get("at_seconds", 0.0)) <= playhead
            }
        elif rewound:
            # Operator rewound — past flags should re-fire on replay.
            self._fired_ids.clear()
        # else: forward playback on unchanged authored state OR the very
        # first tick — ledger stays intact; initial flags fire normally.

        self._last_timeline_flag_revision = timeline_flag_revision
        self._last_playhead = playhead

        due = [
            flag for flag in flags
            if float(flag.get("at_seconds", 0.0)) <= playhead
            and str(flag.get("id", "")) not in self._fired_ids
        ]
        # Append to existing trigger_events (upstream nodes may have emitted
        # their own; cycle-1 panel UF-34 documents this as a single-writer
        # contract for now — TriggerRouter dedups against its own ledger).
        events: list[dict[str, Any]] = list(state.get("trigger_events") or [])
        for flag in due:
            flag_id = str(flag["id"])
            events.append({
                "id": flag_id,
                "kind": str(flag.get("kind", "")),
                "payload": dict(flag.get("payload") or {}),
            })
            self._fired_ids.add(flag_id)
        state["trigger_events"] = events
        return state
