"""Laser zone runtime node — applies authored zone policies to ILDA frames.

Pure transform: clamps brightness to safe DMX range and blanks points on
each fixture's protected half-plane. Reads `state["laser_zone_rules"]`
populated by `ILDAOutputNode`'s zone-policy resolution; mutates
`state["ilda_frames"]` in place before `LaserVectorInterlockNode` sees them.

Cycle-1 panel UF-19 + UF-35: `_channel_clamp` uses `round()` (unbiased)
not `int()` (truncation), and bound-clamps to [0, 255] so out-of-range
inputs cannot produce out-of-range DMX bytes (a physical-fixture safety
concern, not just a policy nit).

Cycle-1 panel UF-20: the protected half-plane is per-fixture
(`safety_protected_half_plane` on FixtureConfig), defaulting to
`(axis="y", threshold=0.0, below_is_protected=True)` for backward
compatibility with cycle-1's hardcoded `y < 0` behavior. Venues with
ceiling-mounted / off-center geometries override on a per-fixture basis.
"""

from __future__ import annotations

from typing import Any

from photonic_synesthesia.core.config import FixtureConfig
from photonic_synesthesia.graph.safety import (
    ProtectedHalfPlane,
    is_point_protected,
    protected_half_plane_for_fixture,
)


def _channel_clamp(value: float) -> int:
    """Clamp a channel value to the [0, 255] DMX byte range with unbiased rounding."""
    if value != value:  # NaN
        return 0
    clamped = max(0.0, min(255.0, value))
    return int(round(clamped))


class LaserZoneRuntimeNode:
    """Apply authored zone policies (brightness cap + protected blanking).

    Cycle-5 panel LS2: the protected-zone predicate is now a shared
    helper in `photonic_synesthesia.graph.safety.protected_zone`.
    `LaserVectorInterlockNode` (the final geometric gate) imports the
    SAME helper, guaranteeing the two nodes can't disagree on whether
    a point is in the protected zone.
    """

    def __init__(self, *, fixtures: list[FixtureConfig] | None = None) -> None:
        self._protected_half_plane_by_fixture: dict[str, ProtectedHalfPlane] = {
            str(f.id): protected_half_plane_for_fixture(f)
            for f in (fixtures or [])
        }

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        rules = state.get("laser_zone_rules") or {}
        frames: list[dict[str, Any]] = []
        for frame in list(state.get("ilda_frames", []) or []):
            updated = dict(frame)
            fixture_id = str(frame.get("fixture_id", ""))
            rule = rules.get(fixture_id, {}) if isinstance(rules, dict) else {}
            # Cycle-5 MEDIUM (Review 2): guard against NaN (propagates
            # through RGB silently) and negative values (would invert
            # colors). Values > 1.0 are explicitly ALLOWED — some rigs
            # intentionally boost dim lasers, and `_channel_clamp` at
            # the final write caps overflow at 255. So the guard is
            # `[0, inf)` with NaN → 0, not `[0, 1]`.
            raw_cap = float(rule.get("brightness_cap", 1.0)) if isinstance(rule, dict) else 1.0
            if raw_cap != raw_cap:  # NaN check (NaN != NaN)
                raw_cap = 0.0
            brightness_cap = max(0.0, raw_cap)
            protected = bool(rule.get("protected", False)) if isinstance(rule, dict) else False
            half_plane = self._protected_half_plane_by_fixture.get(
                fixture_id,
                ProtectedHalfPlane(axis="y", threshold=0.0, below_is_protected=True),
            )
            new_points: list[dict[str, Any]] = []
            for point in list(frame.get("points", []) or []):
                # Cycle-5 LS2: use the shared helper. `point[axis]` is
                # already in ILDA int-space; `half_plane.threshold` is in
                # the SAME space. No rescale anywhere.
                value_on_axis = float(point.get(half_plane.axis, 0.0))
                blanked = bool(point.get("blanked", False)) or (
                    protected and is_point_protected(value_on_axis, half_plane)
                )
                new_points.append({
                    **point,
                    "r": _channel_clamp(float(point.get("r", 0)) * brightness_cap),
                    "g": _channel_clamp(float(point.get("g", 0)) * brightness_cap),
                    "b": _channel_clamp(float(point.get("b", 0)) * brightness_cap),
                    "blanked": blanked,
                })
            updated["points"] = new_points
            frames.append(updated)
        state["ilda_frames"] = frames
        return state
