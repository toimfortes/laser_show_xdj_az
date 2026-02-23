"""
LangGraph Builder for Photonic Synesthesia.

Constructs the main state machine graph that orchestrates all
sensor acquisition, analysis, and fixture control nodes.
"""

from __future__ import annotations

from typing import Any

import structlog
from langgraph.graph import END, StateGraph

from photonic_synesthesia.core.config import Settings
from photonic_synesthesia.core.state import PhotonicState, create_initial_state
from photonic_synesthesia.graph.nodes import (
    AudioSenseNode,
    BeatTrackNode,
    CVSenseNode,
    DirectorIntentNode,
    DMXOutputNode,
    FeatureExtractNode,
    FusionNode,
    InterpreterNode,
    LaserControlNode,
    MidiSenseNode,
    MovingHeadControlNode,
    PanelControlNode,
    SafetyInterlockNode,
    SceneSelectNode,
    StructureDetectNode,
)

logger = structlog.get_logger()


class PhotonicGraph:
    """
    Wrapper around the compiled LangGraph for the photonic synesthesia system.

    Provides methods for running the graph continuously and managing
    the sensor/output lifecycle.
    """

    def __init__(
        self,
        graph: Any,  # Compiled StateGraph
        settings: Settings,
        nodes: dict[str, Any],
    ):
        self.graph = graph
        self.settings = settings
        self.nodes = nodes
        self._running = False
        self._state = create_initial_state()
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
        if "safety_interlock" in self.nodes and hasattr(self.nodes["safety_interlock"], "start"):
            self.nodes["safety_interlock"].start()

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
        if "safety_interlock" in self.nodes and hasattr(self.nodes["safety_interlock"], "stop"):
            self.nodes["safety_interlock"].stop()
        if "dmx_output" in self.nodes:
            self.nodes["dmx_output"].stop()

    def step(self) -> PhotonicState:
        """Execute one iteration of the graph."""
        self._state = self.graph.invoke(self._state)
        return self._state

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
        return self._state


def build_photonic_graph(
    settings: Settings | None = None,
    mock_sensors: bool = False,
) -> PhotonicGraph:
    """
    Build and compile the complete photonic synesthesia graph.

    Args:
        settings: Configuration settings. Uses defaults if None.
        mock_sensors: If True, use mock sensor nodes for testing.

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
    nodes["laser_control"] = LaserControlNode(settings.fixtures, settings.safety.laser)
    nodes["moving_head_control"] = MovingHeadControlNode(
        settings.fixtures, settings.safety.moving_head
    )
    nodes["panel_control"] = PanelControlNode(settings.fixtures)
    nodes["interpreter"] = InterpreterNode(settings.safety)

    # Safety node
    nodes["safety_interlock"] = SafetyInterlockNode(
        settings.safety,
        settings.fixtures,
        dmx_output=nodes["dmx_output"],
    )

    # Build graph
    graph = StateGraph(PhotonicState)

    # Add all nodes
    for name, node in nodes.items():
        graph.add_node(name, node)

    # Define edges
    # Entry point: audio capture
    graph.set_entry_point("audio_sense")

    # Deterministic single-writer flow:
    # LangGraph merge semantics reject concurrent writes to scalar keys
    # (e.g. `timestamp`) unless reducers are explicitly configured.
    # Keep one path per step so each key has a single writer.
    graph.add_edge("audio_sense", "feature_extract")
    graph.add_edge("feature_extract", "beat_track")
    graph.add_edge("beat_track", "structure_detect")
    graph.add_edge("structure_detect", "midi_sense")
    graph.add_edge("midi_sense", "cv_sense")
    graph.add_edge("cv_sense", "fusion")

    # Scene selection after fusion
    graph.add_edge("fusion", "director_intent")
    graph.add_edge("director_intent", "scene_select")

    # Fixture control (sequential for the same reason as above)
    graph.add_edge("scene_select", "laser_control")
    graph.add_edge("laser_control", "moving_head_control")
    graph.add_edge("moving_head_control", "panel_control")
    graph.add_edge("panel_control", "interpreter")

    # Safety check BEFORE committing to DMX universe
    graph.add_edge("interpreter", "safety_interlock")

    # DMX output after safety has validated/clamped commands
    graph.add_edge("safety_interlock", "dmx_output")

    # Loop back for continuous operation
    # Note: In practice, we use run_loop() which handles the iteration
    graph.add_edge("dmx_output", END)

    # Compile
    compiled = graph.compile()

    return PhotonicGraph(compiled, settings, nodes)


def build_minimal_graph(settings: Settings | None = None) -> PhotonicGraph:
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

    graph = StateGraph(PhotonicState)

    for name, node in nodes.items():
        graph.add_node(name, node)

    graph.set_entry_point("audio_sense")
    graph.add_edge("audio_sense", "safety_interlock")
    graph.add_edge("safety_interlock", "dmx_output")
    graph.add_edge("dmx_output", END)

    compiled = graph.compile()
    return PhotonicGraph(compiled, settings, nodes)
