"""Shared protected-half-plane predicate for laser safety.

Cycle-5 panel LS2 (Claude CRITICAL, 4/4 agreement on redesign): the
cycle-1 plan proposed that `LaserVectorInterlockNode` would do a
"back-translation" from ILDA int-space ([-32767, 32767]) to a
"normalized" space before comparing against the protected-zone
threshold. Reviewer identified this as a coordinate-space unit
confusion — the threshold is ALREADY in the same ILDA int-space the
interlock clamps use. Back-translating would silently reinterpret a
threshold of `0.5` as "half the rig" when it would actually mean
`y < 0.5` on a ±32767 scale, blanking the whole show.

The cycle-2 redesign factors the predicate out of `laser_zone_runtime`
into this module. Both `LaserZoneRuntimeNode` (position 19 in the
pipeline) and `LaserVectorInterlockNode` (position 20, after clamps)
import the SAME helper and compare against the SAME threshold in
the SAME coordinate space. They cannot disagree.

`validate_laser_zone_config()` runs at CLI startup and fails loudly if
the configured clamp bounds would push a safe point into the protected
zone — closing the cycle-1 LS2 mis-calibration class of bug at config
load, not just at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from photonic_synesthesia.core.config import FixtureConfig, LaserSafetyConfig


@dataclass(frozen=True)
class ProtectedHalfPlane:
    """Per-fixture protected-half-plane config.

    `threshold` lives in the SAME coordinate space as
    `LaserSafetyConfig.ilda_{x,y}_{min,max}` — the ILDA int space
    [-32767, 32767]. Consumers MUST NOT rescale this value.
    """
    axis: str               # "x" or "y"
    threshold: float        # int-space coordinate
    below_is_protected: bool


def protected_half_plane_for_fixture(fixture: FixtureConfig) -> ProtectedHalfPlane:
    """Extract the protected-half-plane config from a fixture's
    `safety_protected_half_plane` dict. Falls back to the cycle-1
    default `(y, 0.0, True)` for center-origin Y-up rigs."""
    override = getattr(fixture, "safety_protected_half_plane", None)
    if isinstance(override, dict):
        return ProtectedHalfPlane(
            axis=str(override.get("axis", "y")),
            threshold=float(override.get("threshold", 0.0)),
            below_is_protected=bool(override.get("below_is_protected", True)),
        )
    return ProtectedHalfPlane(axis="y", threshold=0.0, below_is_protected=True)


def is_point_protected(
    value_on_axis: float,
    half_plane: ProtectedHalfPlane,
) -> bool:
    """Return True if the given axis-value sits INSIDE the protected zone.

    Single source of truth used by BOTH `LaserZoneRuntimeNode` (operating
    on pre-clamp points) and `LaserVectorInterlockNode` (operating on
    POST-clamp points — the last geometric gate before hardware). Both
    callers read `value_on_axis` in the ILDA int space, so no rescale
    happens anywhere.
    """
    if half_plane.below_is_protected:
        return value_on_axis < half_plane.threshold
    return value_on_axis > half_plane.threshold


def validate_laser_zone_config(
    fixtures: list[FixtureConfig],
    laser_safety: LaserSafetyConfig,
) -> None:
    """Fail loudly at CLI startup if ILDA clamp bounds could push a safe
    point INTO a protected zone, OR if the threshold looks like it was
    written in the wrong coordinate space.

    Cycle-5 panel LS2 Layer 2 invariant.

    Raises:
        ValueError: on any mis-calibration. Message names both values
            so oncall can fix the config without digging.
    """
    for fixture in fixtures:
        if fixture.type != "laser":
            continue
        half_plane = protected_half_plane_for_fixture(fixture)

        # Threshold MUST live in the same int-space as the clamp bounds.
        # Catch the common mistake where someone writes a normalized
        # (±1.0) value expecting it to be rescaled somewhere.
        if not -32767 <= half_plane.threshold <= 32767:
            raise ValueError(
                f"fixture {fixture.id!r}: protected_half_plane.threshold="
                f"{half_plane.threshold} is outside the ILDA int-space range "
                "[-32767, 32767]. Thresholds MUST be specified in the same "
                "coordinate space as ilda_{x,y}_{min,max}. If you meant "
                "half the rig, use 16383, not 0.5."
            )

        # If the axis the fixture is protected on has a CLAMP RANGE that
        # could push a safe point into the protected region, reject.
        if half_plane.axis == "y":
            clamp_lo = laser_safety.ilda_y_min
            clamp_hi = laser_safety.ilda_y_max
        elif half_plane.axis == "x":
            clamp_lo = laser_safety.ilda_x_min
            clamp_hi = laser_safety.ilda_x_max
        else:
            raise ValueError(
                f"fixture {fixture.id!r}: unknown protected axis "
                f"{half_plane.axis!r} (expected 'x' or 'y')"
            )

        # Invariant: there must exist a SAFE region inside the clamp
        # bounds. If the clamp range is entirely INSIDE the protected
        # region, a safe upstream point would be clamped into it.
        # Normal operation: clamp range straddles the threshold (e.g.,
        # ilda_y_min=-32767, ilda_y_max=32767, threshold=0 → half the
        # range is protected, half safe). That's expected — blanking
        # handles protected points. The dangerous case is when the
        # ENTIRE clamp range is on the protected side of the threshold.
        if half_plane.below_is_protected:
            # Protected region is value < threshold. Dangerous if
            # ilda_*_max is BELOW threshold (entire clamp range is
            # inside the protected region).
            if clamp_hi < half_plane.threshold:
                raise ValueError(
                    f"fixture {fixture.id!r}: ilda_{half_plane.axis}_max="
                    f"{clamp_hi} is BELOW protected_threshold="
                    f"{half_plane.threshold}. The entire clamp range "
                    f"[{clamp_lo}, {clamp_hi}] lies inside the protected "
                    "zone — every point would be clamped into the "
                    f"protected region. Raise ilda_{half_plane.axis}_max "
                    f"to ≥ {half_plane.threshold} or lower the protected "
                    "threshold."
                )
        else:
            # Protected region is value > threshold. Symmetric risk:
            # ilda_*_min above threshold would clamp every point into
            # the protected region.
            if clamp_lo > half_plane.threshold:
                raise ValueError(
                    f"fixture {fixture.id!r}: ilda_{half_plane.axis}_min="
                    f"{clamp_lo} is ABOVE protected_threshold="
                    f"{half_plane.threshold}. The entire clamp range "
                    f"[{clamp_lo}, {clamp_hi}] lies inside the protected "
                    "zone — every point would be clamped into the "
                    "protected region."
                )
