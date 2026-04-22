import json
from pathlib import Path

from photonic_synesthesia.core.config import SceneConfig
from photonic_synesthesia.core.state import MusicStructure, create_initial_state
from photonic_synesthesia.graph.nodes.scene_select import SceneSelectNode


def _write_scene(path: Path, scene_id: str) -> None:
    (path / f"{scene_id}.json").write_text(
        json.dumps(
            {
                "name": scene_id,
                "triggers": {"energy_threshold": 0.25},
            }
        )
    )


def test_scene_select_follows_director_target_when_valid(tmp_path: Path) -> None:
    _write_scene(tmp_path, "idle")
    _write_scene(tmp_path, "drop_intense")
    state = create_initial_state()
    state["scene_state"]["current_scene"] = "idle"
    state["director_state"]["target_scene"] = "drop_intense"
    state["director_state"]["allow_scene_transition"] = True

    node = SceneSelectNode(SceneConfig(scenes_dir=tmp_path))
    result = node(state)

    assert result["scene_state"]["pending_scene"] == "drop_intense"
    assert result["scene_state"]["current_scene"] == "idle"
    assert result["processing_times"]["scene_select"] >= 0.0


def test_scene_select_honors_director_transition_gate(tmp_path: Path) -> None:
    _write_scene(tmp_path, "drop_intense")
    _write_scene(tmp_path, "intro_ambient")

    state = create_initial_state()
    state["current_structure"] = MusicStructure.DROP
    state["scene_state"]["current_scene"] = "drop_intense"
    state["director_state"]["target_scene"] = "intro_ambient"
    state["director_state"]["allow_scene_transition"] = False

    node = SceneSelectNode(SceneConfig(scenes_dir=tmp_path))
    result = node(state)

    assert result["scene_state"]["current_scene"] == "drop_intense"
    assert result["scene_state"]["pending_scene"] is None


def test_scene_select_director_gate_treats_falsey_string_values_as_closed(tmp_path: Path) -> None:
    _write_scene(tmp_path, "drop_intense")
    _write_scene(tmp_path, "intro_ambient")

    node = SceneSelectNode(SceneConfig(scenes_dir=tmp_path))
    for raw_gate in ("false", "0"):
        state = create_initial_state()
        state["current_structure"] = MusicStructure.DROP
        state["scene_state"]["current_scene"] = "drop_intense"
        state["director_state"]["target_scene"] = "intro_ambient"
        state["director_state"]["allow_scene_transition"] = raw_gate

        result = node(state)

        assert result["scene_state"]["current_scene"] == "drop_intense"
        assert result["scene_state"]["pending_scene"] is None


def test_scene_select_falls_back_when_director_is_unknown(tmp_path: Path) -> None:
    _write_scene(tmp_path, "drop_intense")
    _write_scene(tmp_path, "intro_ambient")

    state = create_initial_state()
    state["current_structure"] = MusicStructure.DROP
    state["scene_state"]["current_scene"] = "intro_ambient"
    state["director_state"]["target_scene"] = "not_a_scene"
    state["director_state"]["allow_scene_transition"] = True

    node = SceneSelectNode(SceneConfig(scenes_dir=tmp_path))
    result = node(state)

    # Fallback for DROP should remain to loaded drop-intense scene.
    assert result["scene_state"]["pending_scene"] == "drop_intense"


def test_scene_select_uses_active_section_scene_id_after_manual_and_pad_overrides(tmp_path: Path) -> None:
    _write_scene(tmp_path, "idle")
    _write_scene(tmp_path, "drop_intense")
    _write_scene(tmp_path, "intro_ambient")

    state = create_initial_state()
    state["scene_state"]["current_scene"] = "idle"
    state["playback_snapshot"] = {
        "playhead_seconds": 5.0,
        "show_sections": [
            {
                "id": "sec-1",
                "start_seconds": 0.0,
                "end_seconds": 10.0,
                "scene_id": "drop_intense",
            }
        ],
    }
    state["director_state"]["target_scene"] = "intro_ambient"
    state["director_state"]["allow_scene_transition"] = True

    node = SceneSelectNode(SceneConfig(scenes_dir=tmp_path))
    result = node(state)

    assert result["scene_state"]["pending_scene"] == "drop_intense"
    assert result["scene_state"]["current_scene"] == "idle"


def test_scene_select_pad_override_still_beats_section_scene_id(tmp_path: Path) -> None:
    _write_scene(tmp_path, "idle")
    _write_scene(tmp_path, "drop_intense")
    (tmp_path / "intro_ambient.json").write_text(
        json.dumps(
            {
                "name": "intro_ambient",
                "pad_trigger": 1,
                "triggers": {"energy_threshold": 0.25},
            }
        )
    )

    state = create_initial_state()
    state["scene_state"]["current_scene"] = "idle"
    state["midi_state"]["pad_triggers"] = [1]
    state["playback_snapshot"] = {
        "playhead_seconds": 5.0,
        "show_sections": [
            {
                "id": "sec-1",
                "start_seconds": 0.0,
                "end_seconds": 10.0,
                "scene_id": "drop_intense",
            }
        ],
    }

    node = SceneSelectNode(SceneConfig(scenes_dir=tmp_path))
    result = node(state)

    assert result["scene_state"]["pending_scene"] == "intro_ambient"
    assert result["scene_state"]["current_scene"] == "idle"


def test_scene_select_launched_scene_still_beats_section_scene_id(tmp_path: Path) -> None:
    _write_scene(tmp_path, "idle")
    _write_scene(tmp_path, "drop_intense")
    _write_scene(tmp_path, "intro_ambient")

    state = create_initial_state()
    state["scene_state"]["current_scene"] = "idle"
    state["control_state"]["launched_scene"] = "intro_ambient"
    state["playback_snapshot"] = {
        "playhead_seconds": 5.0,
        "show_sections": [
            {
                "id": "sec-1",
                "start_seconds": 0.0,
                "end_seconds": 10.0,
                "scene_id": "drop_intense",
            }
        ],
    }

    node = SceneSelectNode(SceneConfig(scenes_dir=tmp_path))
    result = node(state)

    assert result["scene_state"]["pending_scene"] == "intro_ambient"
    assert result["scene_state"]["current_scene"] == "idle"


def test_scene_select_falls_back_safely_when_active_section_scene_id_is_invalid(tmp_path: Path) -> None:
    _write_scene(tmp_path, "idle")
    _write_scene(tmp_path, "intro_ambient")

    state = create_initial_state()
    state["scene_state"]["current_scene"] = "idle"
    state["playback_snapshot"] = {
        "playhead_seconds": 5.0,
        "show_sections": [
            {
                "id": "sec-1",
                "start_seconds": 0.0,
                "end_seconds": 10.0,
                "scene_id": "not_a_scene",
            }
        ],
    }
    state["director_state"]["target_scene"] = "intro_ambient"
    state["director_state"]["allow_scene_transition"] = True

    node = SceneSelectNode(SceneConfig(scenes_dir=tmp_path))
    result = node(state)

    assert result["scene_state"]["pending_scene"] == "intro_ambient"
    assert result["scene_state"]["current_scene"] == "idle"


def test_scene_select_active_section_scene_id_respects_transition_gate(tmp_path: Path) -> None:
    _write_scene(tmp_path, "idle")
    _write_scene(tmp_path, "idle_calm")
    _write_scene(tmp_path, "drop_intense")

    state = create_initial_state()
    state["scene_state"]["current_scene"] = "idle"
    state["audio_features"]["rms_energy"] = 0.0
    state["playback_snapshot"] = {
        "playhead_seconds": 5.0,
        "show_sections": [
            {
                "id": "sec-1",
                "start_seconds": 0.0,
                "end_seconds": 10.0,
                "scene_id": "drop_intense",
            }
        ],
    }
    state["director_state"]["allow_scene_transition"] = False
    state["director_state"]["target_scene"] = "idle"

    node = SceneSelectNode(SceneConfig(scenes_dir=tmp_path))
    result = node(state)

    assert result["scene_state"]["current_scene"] == "idle"
    assert result["scene_state"]["pending_scene"] is None


def test_scene_select_active_section_gate_treats_falsey_string_values_as_closed(tmp_path: Path) -> None:
    _write_scene(tmp_path, "idle")
    _write_scene(tmp_path, "drop_intense")

    node = SceneSelectNode(SceneConfig(scenes_dir=tmp_path))
    for raw_gate in ("false", "0"):
        state = create_initial_state()
        state["scene_state"]["current_scene"] = "idle"
        state["playback_snapshot"] = {
            "playhead_seconds": 5.0,
            "show_sections": [
                {
                    "id": "sec-1",
                    "start_seconds": 0.0,
                    "end_seconds": 10.0,
                    "scene_id": "drop_intense",
                }
            ],
        }
        state["director_state"]["target_scene"] = "idle"
        state["director_state"]["allow_scene_transition"] = raw_gate

        result = node(state)

        assert result["scene_state"]["current_scene"] == "idle"
        assert result["scene_state"]["pending_scene"] is None


def test_scene_select_short_section_scene_id_only_retargets_pending_scene(tmp_path: Path) -> None:
    _write_scene(tmp_path, "idle")
    _write_scene(tmp_path, "drop_intense")
    _write_scene(tmp_path, "intro_ambient")

    state = create_initial_state()
    state["timestamp"] = 10.0
    state["scene_state"]["current_scene"] = "idle"
    state["scene_state"]["pending_scene"] = "intro_ambient"
    state["scene_state"]["transition_start_time"] = 8.0
    state["playback_snapshot"] = {
        "playhead_seconds": 0.1,
        "show_sections": [
            {
                "id": "sec-1",
                "start_seconds": 0.0,
                "end_seconds": 0.2,
                "scene_id": "drop_intense",
            }
        ],
    }

    node = SceneSelectNode(SceneConfig(scenes_dir=tmp_path, transition_time_s=1.0))
    result = node(state)

    assert result["scene_state"]["pending_scene"] == "drop_intense"
    assert result["scene_state"]["current_scene"] == "idle"
    assert result["scene_state"]["transition_progress"] == 0.0
    assert result["scene_state"]["transition_start_time"] == 10.0


def test_scene_select_prefers_scene_hold_over_director_target(tmp_path: Path) -> None:
    _write_scene(tmp_path, "idle")
    _write_scene(tmp_path, "drop_intense")
    _write_scene(tmp_path, "intro_ambient")

    state = create_initial_state()
    state["scene_state"]["current_scene"] = "drop_intense"
    state["control_state"]["scene_hold"] = "intro_ambient"
    state["director_state"]["target_scene"] = "drop_intense"
    state["playback_snapshot"] = {
        "playhead_seconds": 5.0,
        "show_sections": [
            {
                "id": "sec-1",
                "start_seconds": 0.0,
                "end_seconds": 10.0,
                "scene_id": "drop_intense",
            }
        ],
    }

    node = SceneSelectNode(SceneConfig(scenes_dir=tmp_path))
    result = node(state)

    assert result["scene_state"]["pending_scene"] == "intro_ambient"
