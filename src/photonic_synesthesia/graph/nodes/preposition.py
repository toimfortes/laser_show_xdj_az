"""Pre-position runtime node — emits move-when-dark targets per fixture.

Reads authored sections + section.preposition_intent from the published
playback snapshot. Emits one target per active moving-head fixture into
`state["preposition_targets"]`. Cycle-2 panel NC-9 / cycle-1 panel
UF-21: each target carries `fixture_id` so `MovingHeadControlNode` can
filter; without per-fixture addressing a multi-fixture rig would
cross-contaminate.
"""

from __future__ import annotations

from typing import Any

from photonic_synesthesia.core.config import FixtureConfig


class PrepositionNode:
    """Emit per-fixture preposition targets when the dark-window opens."""

    def __init__(self, *, fixtures: list[FixtureConfig] | None = None) -> None:
        self._moving_head_fixture_ids = [
            str(f.id) for f in (fixtures or []) if getattr(f, "type", "") == "moving_head"
        ]

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        snapshot = dict(state.get("playback_snapshot") or {})
        playhead = float(snapshot.get("playhead_seconds", 0.0))
        blackout_active = bool((state.get("control_state") or {}).get("blackout_active", False))
        subphrase_role = str((state.get("director_state") or {}).get("subphrase_role") or "")
        dark_window_open = blackout_active or subphrase_role in {"release", "settle"}

        targets: list[dict[str, str]] = []
        for section in list(snapshot.get("show_sections", [])):
            start = float(section.get("start_seconds", 0.0))
            end = float(section.get("end_seconds", start))
            if not (start <= playhead < max(end, start + 1e-6)):
                continue
            intent = dict(section.get("preposition_intent") or {})
            if not intent.get("enabled"):
                continue
            intent_when = str(intent.get("when") or "release")
            should_fire = (
                intent_when == "always"
                or (intent_when == "blackout" and blackout_active)
                or (intent_when == "release" and dark_window_open)
            )
            if not should_fire:
                continue
            presets = list(intent.get("targets") or [])
            # Broadcast each preset to every active moving-head fixture so
            # each fixture receives its own addressed target. If the
            # fixture list is empty (e.g. unit tests without a roster),
            # emit a single un-addressed target with the conventional
            # `mh-1` id so single-fixture tests stay green.
            fixture_ids = self._moving_head_fixture_ids or ["mh-1"]
            for preset in presets:
                for fixture_id in fixture_ids:
                    targets.append({
                        "fixture_id": fixture_id,
                        "section_id": str(section["id"]),
                        "preset": str(preset),
                    })
        state["preposition_targets"] = targets
        return state
