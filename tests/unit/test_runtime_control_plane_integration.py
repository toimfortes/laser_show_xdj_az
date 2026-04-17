from unittest import mock

from photonic_synesthesia.core.state import create_initial_state
from photonic_synesthesia.platform import (
    ControlPlaneStateService,
    PlaybackContext,
    clear_shared_control_plane_service,
    clear_shared_playback_context,
    get_shared_control_plane_service,
    get_shared_playback_context,
    set_shared_control_plane_service,
    set_shared_playback_context,
)
from photonic_synesthesia.ui.web_panel import create_app


def test_photonic_graph_step_publishes_snapshot_to_control_plane_service() -> None:
    from photonic_synesthesia.graph.builder import PhotonicGraph

    class _FakeGraph:
        def invoke(self, state):  # type: ignore[override]
            state = create_initial_state()
            state["scene_state"]["current_scene"] = "drop_intense"
            state["frame_number"] = 7
            state["audio_features"]["harmonic_ratio"] = 0.72
            state["audio_features"]["percussive_ratio"] = 0.28
            state["audio_features"]["tonal_stability"] = 0.84
            state["audio_features"]["harmonic_change"] = 0.18
            state["audio_features"]["pitch_salience"] = 0.66
            state["audio_features"]["pitch_height"] = 0.58
            state["audio_features"]["timbral_harshness"] = 0.22
            state["director_state"]["melodic_smoothness"] = 0.79
            state["director_state"]["laser_aggression"] = 0.31
            state["director_state"]["color_drive"] = 0.48
            state["director_state"]["subphrase_role"] = "variation"
            state["director_state"]["fill_pressure"] = 0.66
            state["director_state"]["phrase_intensity"] = 0.82
            return state

    class _FakeILDAOutput:
        def get_stats(self) -> dict[str, object]:
            return {
                "transport_type": "ether_dream",
                "ether_dream_host": "192.0.2.10",
                "ether_dream_faulted": False,
            }

    service = ControlPlaneStateService()
    graph = PhotonicGraph(
        graph=_FakeGraph(),
        settings=mock.MagicMock(),
        nodes={"ilda_output": _FakeILDAOutput()},
        control_plane_service=service,
    )

    snapshot = graph.step()

    assert snapshot["scene_state"]["current_scene"] == "drop_intense"
    assert service.snapshot().active_scene_id == "drop_intense"
    assert service.snapshot().diagnostics["frame_number"] == 7
    assert service.snapshot().semantic_frame.harmonic_ratio == 0.72
    assert service.snapshot().semantic_frame.pitch_salience == 0.66
    assert service.snapshot().director_summary.melodic_smoothness == 0.79
    assert service.snapshot().director_summary.laser_aggression == 0.31
    assert service.snapshot().director_summary.subphrase_role == "variation"
    assert service.snapshot().director_summary.fill_pressure == 0.66
    assert service.snapshot().director_summary.phrase_intensity == 0.82
    assert service.snapshot().diagnostics["ilda_transport_type"] == "ether_dream"
    assert service.snapshot().diagnostics["ilda_transport_host"] == "192.0.2.10"
    assert service.snapshot().diagnostics["ilda_transport_faulted"] is False


def test_web_panel_uses_shared_control_plane_service_by_default() -> None:
    clear_shared_control_plane_service()
    shared = set_shared_control_plane_service(ControlPlaneStateService())
    shared.update_from_photonic_state(create_initial_state(), source="shared_test")

    app = create_app()

    assert app.state.services is shared
    assert get_shared_control_plane_service() is shared

    clear_shared_control_plane_service()


def test_shared_playback_context_is_process_local() -> None:
    clear_shared_playback_context()
    playback = set_shared_playback_context(
        PlaybackContext(
            file_path="/tmp/test.mp3",
            file_name="test.mp3",
            duration_seconds=123.4,
            waveform=[0.1, 0.2, 0.3],
        )
    )
    playback.update_transport(
        playhead_seconds=12.3,
        playing=True,
        finished=False,
        realtime=True,
        speed=1.0,
    )

    assert get_shared_playback_context() is playback
    assert playback.snapshot()["playhead_seconds"] == 12.3
    assert playback.snapshot()["playing"] is True
    assert playback.snapshot()["session_id"] == playback.session_id
    assert playback.snapshot()["transport_revision"] == 1

    clear_shared_playback_context()


def test_playback_snapshot_deep_copies_nested_show_sections() -> None:
    clear_shared_playback_context()
    playback = set_shared_playback_context(
        PlaybackContext(
            file_path="/tmp/test.mp3",
            file_name="test.mp3",
            duration_seconds=123.4,
            show_sections=[
                {
                    "id": "section_001",
                    "laser_program": {
                        "sustain": [
                            {"pattern": "fan", "bars": 4},
                        ]
                    },
                }
            ],
        )
    )

    snapshot = playback.snapshot()
    snapshot["show_sections"][0]["laser_program"]["sustain"][0]["pattern"] = "tunnel"

    assert playback.snapshot()["show_sections"][0]["laser_program"]["sustain"][0]["pattern"] == "fan"

    clear_shared_playback_context()
