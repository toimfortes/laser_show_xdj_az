"""
Sequential Builder for Photonic Synesthesia.

Constructs the main processing pipeline that orchestrates all
sensor acquisition, analysis, and fixture control nodes.
"""

from __future__ import annotations

from threading import Lock
from typing import Any

from photonic_synesthesia.core.config import Settings
from photonic_synesthesia.core.logging import get_logger
from photonic_synesthesia.core.state import PhotonicState, create_initial_state
from photonic_synesthesia.graph.nodes import (
    AudioSenseNode,
    BeatTrackNode,
    CVSenseNode,
    DirectorIntentNode,
    DMXOutputNode,
    FeatureExtractNode,
    FusionNode,
    ILDAOutputNode,
    ILDADACOutputNode,
    InterpreterNode,
    LaserControlNode,
    MidiSenseNode,
    MovingHeadControlNode,
    PanelControlNode,
    SafetyInterlockNode,
    SafetyMonitor,
    SceneSelectNode,
    StructureDetectNode,
    LaserVectorInterlockNode,
)
from photonic_synesthesia.platform import CommandType
from photonic_synesthesia.platform.state_service import ControlPlaneStateService

logger = get_logger(__name__)


class _SequentialPipeline:
    """Simple deterministic node pipeline with single-pass execution."""

    def __init__(self, node_names: list[str], nodes: dict[str, Any]):
        self._node_names = node_names
        self._nodes = nodes

    def invoke(self, state: PhotonicState) -> PhotonicState:
        current_state = state
        for name in self._node_names:
            node = self._nodes[name]
            current_state = node(current_state)
        return current_state


class PhotonicGraph:
    """
    Wrapper around the deterministic node pipeline for the photonic
    synesthesia system.

    Provides methods for running the graph continuously and managing
    the sensor/output lifecycle.
    """

    def __init__(
        self,
        graph: Any,  # Compiled StateGraph
        settings: Settings,
        nodes: dict[str, Any],
        control_plane_service: ControlPlaneStateService | None = None,
        safety_monitor: SafetyMonitor | None = None,
    ):
        self.graph = graph
        self.settings = settings
        self.nodes = nodes
        self.safety_monitor = safety_monitor
        self.control_plane_service = control_plane_service
        self._running = False
        self._state = create_initial_state()
        self._state_lock = Lock()
        self.hybrid_pacing = settings.runtime_flags.hybrid_pacing
        self.dual_loop = settings.runtime_flags.dual_loop

    def start(self) -> None:
        """Start all sensor nodes and begin processing."""
        logger.info("Starting photonic graph")
        self._running = True

        # Start background threads for sensors
        if "audio_sense" in self.nodes:
            self.nodes["audio_sense"].start()
        if "midi_sense" in self.nodes:
            self.nodes["midi_sense"].start()
        if "cv_sense" in self.nodes and hasattr(self.nodes["cv_sense"], "start"):
            self.nodes["cv_sense"].start()
        if "dmx_output" in self.nodes:
            self.nodes["dmx_output"].start()
        if "ilda_output" in self.nodes and hasattr(self.nodes["ilda_output"], "start"):
            self.nodes["ilda_output"].start()
        if "ilda_transport" in self.nodes and hasattr(self.nodes["ilda_transport"], "start"):
            self.nodes["ilda_transport"].start()
        if "safety_interlock" in self.nodes and hasattr(self.nodes["safety_interlock"], "start"):
            self.nodes["safety_interlock"].start()
        if self.safety_monitor is not None:
            self.safety_monitor.start()

    def stop(self) -> None:
        """Stop all processing and clean up resources."""
        logger.info("Stopping photonic graph")
        self._running = False

        # Stop background threads
        if "audio_sense" in self.nodes:
            self.nodes["audio_sense"].stop()
        if "midi_sense" in self.nodes:
            self.nodes["midi_sense"].stop()
        if "cv_sense" in self.nodes and hasattr(self.nodes["cv_sense"], "stop"):
            self.nodes["cv_sense"].stop()
        if "ilda_transport" in self.nodes and hasattr(self.nodes["ilda_transport"], "stop"):
            self.nodes["ilda_transport"].stop()
        if "safety_interlock" in self.nodes and hasattr(self.nodes["safety_interlock"], "stop"):
            self.nodes["safety_interlock"].stop()
        if self.safety_monitor is not None:
            self.safety_monitor.stop()
        if "ilda_output" in self.nodes and hasattr(self.nodes["ilda_output"], "stop"):
            self.nodes["ilda_output"].stop()
        if "dmx_output" in self.nodes:
            self.nodes["dmx_output"].stop()

    def step(self) -> PhotonicState:
        """Execute one iteration of the graph."""
        with self._state_lock:
            self._sync_control_state()
            self._drain_control_commands()
            self._state = self.graph.invoke(self._state)
            if self.control_plane_service is not None:
                node_stats = {
                    name: node.get_stats()
                    for name, node in self.nodes.items()
                    if hasattr(node, "get_stats")
                }
                self.control_plane_service.update_from_photonic_state(
                    self._state,
                    node_stats=node_stats,
                )
            return self._state

    def _drain_control_commands(self) -> None:
        if self.control_plane_service is None:
            return
        commands = self.control_plane_service.commands.drain()
        if not commands:
            return

        should_blackout = False
        should_clear_blackout = False
        for command in commands:
            if command.command_type in {CommandType.BLACKOUT, CommandType.DISARM}:
                should_blackout = True
            if command.command_type == CommandType.CLEAR_BLACKOUT:
                should_clear_blackout = True

        if should_blackout:
            self._request_blackout()
        elif should_clear_blackout and self._state["control_state"]["armed_live"]:
            self._clear_blackout()

    def _sync_control_state(self) -> None:
        if self.control_plane_service is None:
            return
        self._state["control_state"].update(
            self.control_plane_service.consume_control_snapshot_for_graph(),
        )

    def _request_blackout(self) -> None:
        dmx_output = self.nodes.get("dmx_output")
        if dmx_output is not None and hasattr(dmx_output, "request_blackout"):
            dmx_output.request_blackout()
        for ilda_output in (
            self.nodes.get("ilda_output"),
            self.nodes.get("ilda_transport"),
        ):
            if ilda_output is not None and hasattr(ilda_output, "request_blackout"):
                ilda_output.request_blackout()

    def _clear_blackout(self) -> None:
        dmx_output = self.nodes.get("dmx_output")
        if dmx_output is not None and hasattr(dmx_output, "clear_blackout_request"):
            dmx_output.clear_blackout_request()
        for ilda_output in (
            self.nodes.get("ilda_output"),
            self.nodes.get("ilda_transport"),
        ):
            if ilda_output is not None and hasattr(ilda_output, "clear_blackout_request"):
                ilda_output.clear_blackout_request()

    def run_loop(self, target_fps: float = 50.0) -> None:
        """Run the graph in a continuous loop at target FPS."""
        import time

        frame_time = 1.0 / target_fps
        if self.dual_loop:
            logger.warning(
                "Dual-loop runtime flag is enabled, but single-loop execution path is active",
            )

        try:
            self.start()
            while self._running:
                start = time.perf_counter()
                self.step()
                elapsed = time.perf_counter() - start

                # Sleep to maintain target FPS
                sleep_time = frame_time - elapsed
                if sleep_time > 0:
                    if self.hybrid_pacing:
                        self._sleep_with_hybrid_pacing(sleep_time)
                    else:
                        time.sleep(sleep_time)
                elif self.settings.debug:
                    logger.warning(
                        "Frame overrun",
                        elapsed_ms=elapsed * 1000,
                        target_ms=frame_time * 1000,
                    )
        finally:
            self.stop()

    @staticmethod
    def _sleep_with_hybrid_pacing(sleep_time: float) -> None:
        """
        Use coarse sleep plus a short spin/yield tail for tighter frame pacing.
        """
        import time

        if sleep_time <= 0:
            return
        deadline = time.perf_counter() + sleep_time
        coarse = sleep_time - 0.002
        if coarse > 0:
            time.sleep(coarse)
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                break
            if remaining > 0.0005:
                time.sleep(0)

    @property
    def state(self) -> PhotonicState:
        """Get current state."""
        with self._state_lock:
            return self._state


def build_photonic_graph(
    settings: Settings | None = None,
    mock_sensors: bool = False,
    control_plane_service: ControlPlaneStateService | None = None,
    node_overrides: dict[str, Any] | None = None,
) -> PhotonicGraph:
    """
    Build and compile the complete photonic synesthesia graph.

    Args:
        settings: Configuration settings. Uses defaults if None.
        mock_sensors: If True, use mock sensor nodes for testing.
        node_overrides: Optional node implementations keyed by graph node name.

    Returns:
        Compiled PhotonicGraph ready for execution.
    """
    if settings is None:
        settings = Settings()

    logger.info("Building photonic graph", mock_sensors=mock_sensors)

    # Initialize nodes
    nodes: dict[str, Any] = {}

    if mock_sensors:
        from photonic_synesthesia.graph.nodes.mocks import (
            MockAudioSenseNode,
            MockCVSenseNode,
            MockDMXOutputNode,
            MockMidiSenseNode,
        )

        nodes["audio_sense"] = MockAudioSenseNode()
        nodes["midi_sense"] = MockMidiSenseNode()
        nodes["cv_sense"] = MockCVSenseNode()
        nodes["dmx_output"] = MockDMXOutputNode()
    else:
        nodes["audio_sense"] = AudioSenseNode(settings.audio)
        nodes["midi_sense"] = MidiSenseNode(settings.midi)
        nodes["cv_sense"] = CVSenseNode(
            settings.cv,
            cv_threaded=settings.runtime_flags.cv_threaded,
        )
        nodes["dmx_output"] = DMXOutputNode(
            settings.dmx,
            dmx_double_buffer=settings.runtime_flags.dmx_double_buffer,
        )

    # Analysis nodes (always real)
    nodes["feature_extract"] = FeatureExtractNode(
        streaming_dsp=settings.runtime_flags.streaming_dsp
    )
    nodes["beat_track"] = BeatTrackNode(settings.beat_tracking)
    nodes["structure_detect"] = StructureDetectNode(settings.structure_detection)
    nodes["fusion"] = FusionNode()
    nodes["director_intent"] = DirectorIntentNode()
    nodes["scene_select"] = SceneSelectNode(settings.scene)

    # Fixture control nodes
    nodes["laser_control"] = LaserControlNode(
        settings.fixtures,
        settings.safety.laser,
        fixtures_dir=settings.fixtures_dir,
    )
    nodes["moving_head_control"] = MovingHeadControlNode(
        settings.fixtures, settings.safety.moving_head
    )
    nodes["panel_control"] = PanelControlNode(settings.fixtures)
    nodes["interpreter"] = InterpreterNode(settings.safety)
    nodes["ilda_output"] = ILDAOutputNode(
        settings.ilda,
        settings.fixtures,
        settings.safety.laser,
        fixtures_dir=settings.fixtures_dir,
    )
    nodes["ilda_transport"] = ILDADACOutputNode(
        settings.ilda,
        settings.safety.laser,
        settings.fixtures,
    )

    # Safety node
    nodes["safety_interlock"] = SafetyInterlockNode(
        settings.safety,
        settings.fixtures,
        dmx_output=nodes["dmx_output"],
        ilda_output=nodes["ilda_transport"],
    )
    safety_monitor = SafetyMonitor(
        dmx_output=nodes["dmx_output"],
        ilda_output=nodes["ilda_transport"],
        check_interval=0.1,
        max_silence=max(0.5 * settings.safety.heartbeat_timeout_s, 0.05),
    )
    nodes["laser_vector_interlock"] = LaserVectorInterlockNode(settings.safety.laser)

    if node_overrides:
        nodes.update(node_overrides)

    pipeline = _SequentialPipeline(
        node_names=[
            "audio_sense",
            "feature_extract",
            "beat_track",
            "structure_detect",
            "midi_sense",
            "cv_sense",
            "fusion",
            "director_intent",
            "scene_select",
            "laser_control",
            "moving_head_control",
            "panel_control",
            "interpreter",
            "safety_interlock",
            "ilda_output",
            "laser_vector_interlock",
            "ilda_transport",
            "dmx_output",
        ],
        nodes=nodes,
    )

    return PhotonicGraph(
        pipeline,
        settings,
        nodes,
        control_plane_service=control_plane_service,
        safety_monitor=safety_monitor,
    )


def build_minimal_graph(
    settings: Settings | None = None,
    control_plane_service: ControlPlaneStateService | None = None,
) -> PhotonicGraph:
    """
    Build a minimal graph for testing DMX output only.

    Useful for fixture calibration and basic testing without
    full audio analysis.
    """
    if settings is None:
        settings = Settings()

    from photonic_synesthesia.graph.nodes.mocks import MockAudioSenseNode

    dmx_output = DMXOutputNode(
        settings.dmx,
        dmx_double_buffer=settings.runtime_flags.dmx_double_buffer,
    )
    nodes = {
        "audio_sense": MockAudioSenseNode(),
        "dmx_output": dmx_output,
        "safety_interlock": SafetyInterlockNode(
            settings.safety,
            settings.fixtures,
            dmx_output=dmx_output,
        ),
    }
    safety_monitor = SafetyMonitor(
        dmx_output=dmx_output,
        check_interval=0.1,
        max_silence=max(0.5 * settings.safety.heartbeat_timeout_s, 0.05),
    )

    pipeline = _SequentialPipeline(
        node_names=[
            "audio_sense",
            "safety_interlock",
            "dmx_output",
        ],
        nodes=nodes,
    )
    return PhotonicGraph(
        pipeline,
        settings,
        nodes,
        control_plane_service=control_plane_service,
        safety_monitor=safety_monitor,
    )
