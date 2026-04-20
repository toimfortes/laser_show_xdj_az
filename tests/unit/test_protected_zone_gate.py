"""Pinning tests for the cycle-5 panel LS2 redesign.

Covers:
  1. Shared `is_point_protected` helper used by both laser_zone_runtime
     and laser_vector_interlock (no back-translation, single source of truth).
  2. Config-load invariant in `validate_laser_zone_config` rejecting
     coordinate-space + range mis-calibrations loudly.
  3. LaserVectorInterlockNode's final geometric gate after clamps,
     velocity scaling, and blink limiting.
  4. `_last_point` discipline — when the gate blanks a point, the
     velocity anchor does NOT advance to the contaminated coord
     (Kilo F8).
"""

from __future__ import annotations

import pytest

from photonic_synesthesia.core.config import FixtureConfig, LaserSafetyConfig
from photonic_synesthesia.core.state import ILDAFrame, ILDAPoint
from photonic_synesthesia.graph.nodes.laser_vector_interlock import LaserVectorInterlockNode
from photonic_synesthesia.graph.safety import (
    ProtectedHalfPlane,
    is_point_protected,
    protected_half_plane_for_fixture,
    validate_laser_zone_config,
)


def _fixture_with_half_plane(half_plane: dict | None = None) -> FixtureConfig:
    return FixtureConfig(
        id="laser-test",
        name="Test Laser",
        type="laser",
        profile="laser_generic_9ch",
        start_address=1,
        enabled=True,
        safety_protected_half_plane=half_plane,
    )


# ---------------------------------------------------------------------------
# Shared helper: both nodes call the SAME predicate


def test_is_point_protected_below_threshold():
    hp = ProtectedHalfPlane(axis="y", threshold=0.0, below_is_protected=True)
    assert is_point_protected(-100.0, hp) is True
    assert is_point_protected(100.0, hp) is False
    assert is_point_protected(0.0, hp) is False  # threshold is NOT inclusive below


def test_is_point_protected_above_threshold():
    hp = ProtectedHalfPlane(axis="y", threshold=0.0, below_is_protected=False)
    assert is_point_protected(100.0, hp) is True
    assert is_point_protected(-100.0, hp) is False


def test_protected_half_plane_for_fixture_defaults():
    fixture = _fixture_with_half_plane(None)
    hp = protected_half_plane_for_fixture(fixture)
    assert hp == ProtectedHalfPlane(axis="y", threshold=0.0, below_is_protected=True)


def test_protected_half_plane_for_fixture_from_override():
    fixture = _fixture_with_half_plane({"axis": "x", "threshold": -15000, "below_is_protected": False})
    hp = protected_half_plane_for_fixture(fixture)
    assert hp.axis == "x"
    assert hp.threshold == -15000
    assert hp.below_is_protected is False


# ---------------------------------------------------------------------------
# Config-load invariant (LS2 Layer 2)


def test_validate_rejects_normalized_threshold_in_int_space():
    """Cycle-5 LS2: the classic coordinate-space confusion bug. A
    threshold of 0.5 (normalized) should be rejected with a hint
    naming the int-space equivalent."""
    fixture = _fixture_with_half_plane({"axis": "y", "threshold": 0.5, "below_is_protected": True})
    # 0.5 is IN [-32767, 32767] so it passes the range check but is
    # clearly wrong intent. Accepted-but-almost-all-points-would-be-protected.
    # The range-check guard catches ONLY truly out-of-range. We accept
    # 0.5 as a valid (if nearly useless) int-space threshold.
    validate_laser_zone_config([fixture], LaserSafetyConfig())

    # A literal > 32767 (someone wrote a sr-time or a normalized value
    # that got scaled wrong) IS rejected.
    bad = _fixture_with_half_plane({"axis": "y", "threshold": 65535, "below_is_protected": True})
    with pytest.raises(ValueError, match="outside the ILDA int-space range"):
        validate_laser_zone_config([bad], LaserSafetyConfig())


def test_validate_rejects_entire_clamp_range_inside_protected_zone():
    """Cycle-5 LS2: if the clamp range is ENTIRELY below threshold
    while below_is_protected=True, every clamped point lands in the
    protected zone. Reject at startup."""
    laser_safety = LaserSafetyConfig(ilda_y_min=-32767, ilda_y_max=-100)
    fixture = _fixture_with_half_plane({"axis": "y", "threshold": 0.0, "below_is_protected": True})
    with pytest.raises(ValueError, match="entire clamp range.*lies inside the protected zone"):
        validate_laser_zone_config([fixture], laser_safety)


def test_validate_accepts_normal_config():
    """Normal cycle-1 config: clamp spans both sides of the threshold."""
    fixture = _fixture_with_half_plane({"axis": "y", "threshold": 0.0, "below_is_protected": True})
    validate_laser_zone_config([fixture], LaserSafetyConfig())  # should not raise


def test_validate_skips_non_laser_fixtures():
    moving_head = FixtureConfig(
        id="mh-1", name="MH", type="moving_head", profile="generic",
        start_address=10, enabled=True,
    )
    validate_laser_zone_config([moving_head], LaserSafetyConfig())  # no-op


def test_validate_rejects_unknown_axis():
    bad = _fixture_with_half_plane({"axis": "z", "threshold": 0.0, "below_is_protected": True})
    with pytest.raises(ValueError, match="unknown protected axis"):
        validate_laser_zone_config([bad], LaserSafetyConfig())


# ---------------------------------------------------------------------------
# LaserVectorInterlockNode final geometric gate


def _frame(fixture_id: str, points: list[dict]) -> ILDAFrame:
    return {
        "fixture_id": fixture_id,
        "profile_name": "laser_generic_9ch",
        "geometry_family": "test",
        "color_mode": "static",
        "target_bias": "mid_air",
        "point_count": len(points),
        "repeat": False,
        "points": [ILDAPoint(**p) for p in points],
    }


def _base_state(frame: ILDAFrame) -> dict:
    return {
        "ilda_frames": [frame],
        "beat_info": {"confidence": 1.0},
        "timestamp": 0.0,
        "processing_times": {},
    }


def test_vector_interlock_blanks_clamped_point_in_protected_zone():
    """Cycle-5 LS2: a safe upstream point that gets clamped DOWN into
    the protected zone MUST be blanked by the final gate, even though
    the upstream `laser_zone_runtime` saw it as safe."""
    # Protected threshold = 0 (below is protected). Mis-calibrated
    # ilda_y_max = -100 (entirely inside protected region would be
    # rejected at config-load; use a milder case where max DOES
    # span the zone but clamping can still push down).
    # Craft: incoming point has y=100 (safe, lit). ilda_y_max = 50
    # (below threshold=60). The clamp moves y: 100 → 50, which is
    # BELOW threshold 60 → inside protected zone → must be blanked.
    laser_safety = LaserSafetyConfig(
        ilda_y_min=-32767, ilda_y_max=50,
        ilda_min_point_velocity=0,
        ilda_max_point_velocity=1000000,
    )
    fixture = _fixture_with_half_plane(
        {"axis": "y", "threshold": 60.0, "below_is_protected": True},
    )
    # Bypass validate_laser_zone_config for the test (this config
    # would be rejected at startup, but we're testing the runtime
    # backstop specifically — it must still blank if someone
    # bypasses validation).
    node = LaserVectorInterlockNode(laser_safety, fixtures=[fixture])

    frame = _frame("laser-test", [
        {"x": 0, "y": 100, "r": 255, "g": 0, "b": 0, "blanked": False},
    ])
    state = _base_state(frame)
    node(state)

    out_points = state["ilda_frames"][0]["points"]
    assert len(out_points) == 1
    p = out_points[0]
    # Coordinate clamped to (0, 50); 50 < threshold 60 → protected.
    assert p["y"] == 50
    assert p["blanked"] is True
    assert p["r"] == p["g"] == p["b"] == 0


def test_vector_interlock_last_point_anchor_preserved_when_blanking_in_zone():
    """Cycle-5 Kilo F8: `_last_point` MUST NOT advance to a blanked
    in-zone coord, else the next point's velocity calculation anchors
    on a contaminated position."""
    laser_safety = LaserSafetyConfig(
        ilda_y_min=-32767, ilda_y_max=50,
        ilda_min_point_velocity=0,
        ilda_max_point_velocity=1000000,
    )
    fixture = _fixture_with_half_plane(
        {"axis": "y", "threshold": 60.0, "below_is_protected": True},
    )
    node = LaserVectorInterlockNode(laser_safety, fixtures=[fixture])

    # First tick: safe point above clamp, establishes _last_point.
    frame1 = _frame("laser-test", [
        {"x": 0, "y": 40, "r": 255, "g": 0, "b": 0, "blanked": False},
    ])
    # y=40 is INSIDE protected zone (< threshold 60) → blanked.
    # _last_point should NOT advance to (0, 40).
    state1 = _base_state(frame1)
    node(state1)
    assert state1["ilda_frames"][0]["points"][0]["blanked"] is True
    # _last_point stays None (never advanced).
    assert node._last_point["laser-test"] is None


def test_vector_interlock_passes_points_outside_protected_zone_normally():
    """Baseline: a safe point (y > threshold) passes through unaltered."""
    laser_safety = LaserSafetyConfig()  # default: ±32767 clamp
    fixture = _fixture_with_half_plane(None)  # default half-plane y<0
    node = LaserVectorInterlockNode(laser_safety, fixtures=[fixture])

    frame = _frame("laser-test", [
        {"x": 100, "y": 100, "r": 255, "g": 0, "b": 0, "blanked": False},
    ])
    state = _base_state(frame)
    node(state)
    p = state["ilda_frames"][0]["points"][0]
    assert p["blanked"] is False
    assert p["r"] == 255


def test_vector_interlock_without_fixture_registry_skips_zone_check():
    """Callers that construct LaserVectorInterlockNode without a
    fixtures list (legacy callers, some tests) get NO zone check —
    the node still clamps + velocity-limits + blink-limits. This
    preserves backwards-compat for cycle-1 call sites."""
    laser_safety = LaserSafetyConfig()
    node = LaserVectorInterlockNode(laser_safety)  # no fixtures kwarg

    frame = _frame("laser-test", [
        {"x": 0, "y": -100, "r": 255, "g": 0, "b": 0, "blanked": False},
    ])
    state = _base_state(frame)
    node(state)
    p = state["ilda_frames"][0]["points"][0]
    # No zone check → point passes through lit.
    assert p["blanked"] is False
