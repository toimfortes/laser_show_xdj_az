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


def _channel_clamp(value: float) -> int:
    """Clamp a channel value to the [0, 255] DMX byte range with unbiased rounding."""
    if value != value:  # NaN
        return 0
    clamped = max(0.0, min(255.0, value))
    return int(round(clamped))


class LaserZoneRuntimeNode:
    """Apply authored zone policies (brightness cap + protected blanking)."""

    def __init__(self, *, fixtures: list[FixtureConfig] | None = None) -> None:
        self._protected_half_plane_by_fixture = {
            str(f.id): self._protected_half_plane_for_fixture(f)
            for f in (fixtures or [])
        }

    @staticmethod
    def _protected_half_plane_for_fixture(fixture: FixtureConfig) -> tuple[str, float, bool]:
        """Return (axis, threshold, below_is_protected) from the fixture config.

        Default `(y, 0.0, True)` matches cycle-1's hardcoded `y < 0` for
        center-origin Y-up rigs.
        """
        override = getattr(fixture, "safety_protected_half_plane", None)
        if isinstance(override, dict):
            return (
                str(override.get("axis", "y")),
                float(override.get("threshold", 0.0)),
                bool(override.get("below_is_protected", True)),
            )
        return ("y", 0.0, True)

    @staticmethod
    def _point_is_protected(
        point: dict[str, Any],
        axis: str,
        threshold: float,
        below_is_protected: bool,
    ) -> bool:
        value = float(point.get(axis, 0.0))
        return (value < threshold) if below_is_protected else (value > threshold)

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        rules = state.get("laser_zone_rules") or {}
        frames: list[dict[str, Any]] = []
        for frame in list(state.get("ilda_frames", []) or []):
            updated = dict(frame)
            fixture_id = str(frame.get("fixture_id", ""))
            rule = rules.get(fixture_id, {}) if isinstance(rules, dict) else {}
            brightness_cap = float(rule.get("brightness_cap", 1.0)) if isinstance(rule, dict) else 1.0
            protected = bool(rule.get("protected", False)) if isinstance(rule, dict) else False
            axis, threshold, below_is_protected = self._protected_half_plane_by_fixture.get(
                fixture_id, ("y", 0.0, True),
            )
            new_points: list[dict[str, Any]] = []
            for point in list(frame.get("points", []) or []):
                blanked = bool(point.get("blanked", False)) or (
                    protected and self._point_is_protected(point, axis, threshold, below_is_protected)
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
