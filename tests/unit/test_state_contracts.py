"""Task 1 acceptance: PhotonicState carries professional-rollout artifacts.

Pins the five frame-local fields added in Task 1 Step 8 + their initial
values from `create_initial_state()`. Cycle-1 panel SF-3: explicit
per-tick reset is the responsibility of the graph publisher (Task 3
Step 5); this test only proves the fields exist and are typed.
"""

from __future__ import annotations

from photonic_synesthesia.core.state import PhotonicState, create_initial_state


def test_photonic_state_includes_professional_rollout_artifacts() -> None:
    state = create_initial_state()
    assert state["playback_snapshot"] == {}
    assert state["trigger_events"] == []
    assert state["preposition_targets"] == []
    assert state["surface_layers"] == []
    assert state["laser_zone_rules"] == {}


def test_photonic_state_artifact_types_are_mutable_per_tick() -> None:
    """Frame-local artifacts must be writable each tick."""
    state = create_initial_state()
    state["playback_snapshot"] = {"show_sections": [{"id": "x"}]}
    state["trigger_events"].append({"id": "f", "kind": "phrase_head", "payload": {}})
    state["preposition_targets"].append({"fixture_id": "mh-1", "preset": "fan_open"})
    state["surface_layers"].append({"fixture_id": "panel-1", "surface_mode": "texture"})
    state["laser_zone_rules"]["laser-1"] = {"brightness_cap": 1.0}
    assert state["playback_snapshot"]["show_sections"][0]["id"] == "x"
    assert state["trigger_events"][0]["id"] == "f"
    assert state["preposition_targets"][0]["fixture_id"] == "mh-1"
    assert state["surface_layers"][0]["fixture_id"] == "panel-1"
    assert state["laser_zone_rules"]["laser-1"]["brightness_cap"] == 1.0
