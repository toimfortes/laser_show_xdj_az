"""Surface compositor runtime node — emits LED/content layers.

Reads section.surface_program from the published playback snapshot and
emits one layer per (active section, matching panel fixture).

Cycle-2 panel NC-9 fix: the cycle-2 plan emitted layers with
`fixture_id=target` where `target` could be a group label like
"led_wall"; panels filtering by their own id then received no layers
and silently went dark. Cycle 3 takes a fixture roster at construction
time, maps group-label targets to the set of panels in that group, and
emits one layer per (section, matching panel). Unknown targets fall
through with a one-time warning and the opaque label as `fixture_id`.
"""

from __future__ import annotations

from typing import Any

from photonic_synesthesia.core.config import FixtureConfig
from photonic_synesthesia.core.logging import get_logger

logger = get_logger(__name__)


class SurfaceCompositorNode:
    """Per-fixture surface-layer emission with group-label expansion."""

    def __init__(self, *, fixtures: list[FixtureConfig] | None = None) -> None:
        panel_fixtures = [
            f for f in (fixtures or []) if getattr(f, "type", "") == "panel"
        ]
        self._panel_fixture_ids: set[str] = {str(f.id) for f in panel_fixtures}
        self._panel_group_to_ids: dict[str, list[str]] = {}
        for f in panel_fixtures:
            group = getattr(f, "surface_group", None)
            if group:
                self._panel_group_to_ids.setdefault(str(group), []).append(str(f.id))
        self._warned_unknown_targets: set[str] = set()

    def _resolve_target_fixture_ids(self, target: str) -> list[str]:
        if target in self._panel_fixture_ids:
            return [target]
        if target in self._panel_group_to_ids:
            return list(self._panel_group_to_ids[target])
        if target not in self._warned_unknown_targets:
            self._warned_unknown_targets.add(target)
            logger.warning(
                "SurfaceCompositor received unknown target",
                target=target,
            )
        return [target]

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        snapshot = dict(state.get("playback_snapshot") or {})
        playhead = float(snapshot.get("playhead_seconds", 0.0))
        layers: list[dict[str, str]] = []
        for section in list(snapshot.get("show_sections", [])):
            start = float(section.get("start_seconds", 0.0))
            end = float(section.get("end_seconds", start))
            if not (start <= playhead < max(end, start + 1e-6)):
                continue
            program = dict(section.get("surface_program") or {})
            if not program:
                continue
            target = str(program.get("target", ""))
            if not target:
                continue
            surface_mode = str(program.get("surface_mode", "accent"))
            section_id = str(section["id"])
            for fixture_id in self._resolve_target_fixture_ids(target):
                layers.append({
                    "fixture_id": fixture_id,
                    "section_id": section_id,
                    "surface_mode": surface_mode,
                    "target": target,
                })
        state["surface_layers"] = layers
        return state
