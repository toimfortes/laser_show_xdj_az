from unittest.mock import patch

from photonic_synesthesia.core.config import Settings
from photonic_synesthesia.graph.builder import build_minimal_graph, build_photonic_graph


class _NoopNode:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.start_calls = 0
        self.stop_calls = 0

    def __call__(self, state: object) -> object:
        return state

    def start(self) -> None:
        self.start_calls += 1

    def stop(self) -> None:
        self.stop_calls += 1


class _FakeSafetyMonitor:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.start_calls = 0
        self.stop_calls = 0

    def start(self) -> None:
        self.start_calls += 1

    def stop(self) -> None:
        self.stop_calls += 1


def test_minimal_graph_keeps_safety_monitor_outside_orchestration_pipeline() -> None:
    safety_monitor = _FakeSafetyMonitor()

    with patch("photonic_synesthesia.graph.nodes.mocks.MockAudioSenseNode", return_value=_NoopNode()), patch(
        "photonic_synesthesia.graph.builder.DMXOutputNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.builder.SafetyInterlockNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.builder.SafetyMonitor",
        return_value=safety_monitor,
    ):
        graph = build_minimal_graph(settings=Settings())

    assert "safety_monitor" not in graph.nodes
    assert graph.safety_monitor is safety_monitor

    graph.start()
    graph.stop()

    assert safety_monitor.start_calls == 1
    assert safety_monitor.stop_calls == 1


def test_photonic_graph_builds_without_safety_monitor_node_in_graph() -> None:
    safety_monitor = _FakeSafetyMonitor()

    with patch("photonic_synesthesia.graph.nodes.mocks.MockAudioSenseNode", return_value=_NoopNode()), patch(
        "photonic_synesthesia.graph.nodes.mocks.MockMidiSenseNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.nodes.mocks.MockCVSenseNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.nodes.mocks.MockDMXOutputNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.builder.FeatureExtractNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.builder.BeatTrackNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.builder.StructureDetectNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.builder.FusionNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.builder.DirectorIntentNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.builder.SceneSelectNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.builder.LaserControlNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.builder.MovingHeadControlNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.builder.PanelControlNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.builder.InterpreterNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.builder.ILDAOutputNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.builder.ILDADACOutputNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.builder.SafetyInterlockNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.builder.LaserVectorInterlockNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.builder.SafetyMonitor",
        return_value=safety_monitor,
    ):
        graph = build_photonic_graph(settings=Settings(), mock_sensors=True)

    assert "safety_monitor" not in graph.nodes
    assert graph.safety_monitor is safety_monitor


def test_minimal_graph_pipeline_order_is_linear() -> None:
    safety_monitor = _FakeSafetyMonitor()

    with patch("photonic_synesthesia.graph.nodes.mocks.MockAudioSenseNode", return_value=_NoopNode()), patch(
        "photonic_synesthesia.graph.builder.DMXOutputNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.builder.SafetyInterlockNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.builder.SafetyMonitor",
        return_value=safety_monitor,
    ):
        graph = build_minimal_graph(settings=Settings())

    assert graph.graph._node_names == ["audio_sense", "safety_interlock", "dmx_output"]  # type: ignore[attr-defined]


def test_full_graph_pipeline_order_is_linear() -> None:
    safety_monitor = _FakeSafetyMonitor()

    with patch("photonic_synesthesia.graph.nodes.mocks.MockAudioSenseNode", return_value=_NoopNode()), patch(
        "photonic_synesthesia.graph.nodes.mocks.MockMidiSenseNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.nodes.mocks.MockCVSenseNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.nodes.mocks.MockDMXOutputNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.builder.FeatureExtractNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.builder.BeatTrackNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.builder.StructureDetectNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.builder.FusionNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.builder.DirectorIntentNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.builder.SceneSelectNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.builder.LaserControlNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.builder.MovingHeadControlNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.builder.PanelControlNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.builder.InterpreterNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.builder.ILDAOutputNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.builder.ILDADACOutputNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.builder.SafetyInterlockNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.builder.LaserVectorInterlockNode",
        return_value=_NoopNode(),
    ), patch(
        "photonic_synesthesia.graph.builder.SafetyMonitor",
        return_value=safety_monitor,
    ):
        graph = build_photonic_graph(settings=Settings(), mock_sensors=True)

    node_names = graph.graph._node_names  # type: ignore[attr-defined]

    # Professional rollout (Task 3): trigger_router / preposition /
    # surface_compositor land between scene_select and laser_control;
    # laser_zone_runtime lands between ilda_output and laser_vector_interlock.
    expected_prefix = [
        "audio_sense",
        "feature_extract",
        "beat_track",
        "structure_detect",
        "midi_sense",
        "cv_sense",
        "fusion",
        "director_intent",
        "scene_select",
        "trigger_router",
        "preposition",
        "surface_compositor",
        "laser_control",
        "moving_head_control",
        "panel_control",
        "interpreter",
    ]
    expected_suffix = [
        "safety_interlock",
        "ilda_output",
        "laser_zone_runtime",
        "laser_vector_interlock",
        "ilda_transport",
        "dmx_output",
    ]
    assert node_names == expected_prefix + expected_suffix  # type: ignore[comparison-overlap]
