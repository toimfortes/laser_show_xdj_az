"""
LangGraph Builder for Photonic Synesthesia.

Constructs the main state machine graph that orchestrates all
sensor acquisition, analysis, and fixture control nodes.
"""

from __future__ import annotations

from typing import Optional, Dict, Any, Callable
import structlog
from langgraph.graph import StateGraph, END

from photonic_synesthesia.core.state import PhotonicState, create_initial_state
from photonic_synesthesia.core.config import Settings
from photonic_synesthesia.graph.nodes import (
    AudioSenseNode,
    FeatureExtractNode,
    BeatTrackNode,
    StructureDetectNode,
    MidiSenseNode,
    CVSenseNode,
    FusionNode,
    SceneSelectNode,
    LaserControlNode,
    MovingHeadControlNode,
    PanelControlNode,
    DMXOutputNode,
    SafetyInterlockNode,
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
        nodes: Dict[str, Any],
    ):
        self.graph = graph
        self.settings = settings
        self.nodes = nodes
        self._running = False
        self._state = create_initial_state()

    def start(self) -> None:
        """Start all sensor nodes and begin processing."""
        logger.info("Starting photonic graph")
        self._running = True

        # Start background threads for sensors
        if "audio_sense" in self.nodes:
            self.nodes["audio_sense"].start()
        if "midi_sense" in self.nodes:
            self.nodes["midi_sense"].start()
        if "dmx_output" in self.nodes:
            self.nodes["dmx_output"].start()

    def stop(self) -> None:
        """Stop all processing and clean up resources."""
        logger.info("Stopping photonic graph")
        self._running = False

        # Stop background threads
        if "audio_sense" in self.nodes:
            self.nodes["audio_sense"].stop()
        if "midi_sense" in self.nodes:
            self.nodes["midi_sense"].stop()
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

        self.start()
        try:
            while self._running:
                start = time.time()
                self.step()
                elapsed = time.time() - start

                # Sleep to maintain target FPS
                sleep_time = frame_time - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)
                elif self.settings.debug:
                    logger.warning(
                        "Frame overrun",
                        elapsed_ms=elapsed * 1000,
                        target_ms=frame_time * 1000,
                    )
        finally:
            self.stop()

    @property
    def state(self) -> PhotonicState:
        """Get current state."""
        return self._state


def build_photonic_graph(
    settings: Optional[Settings] = None,
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
    nodes: Dict[str, Any] = {}

    if mock_sensors:
        from photonic_synesthesia.graph.nodes.mocks import (
            MockAudioSenseNode,
            MockMidiSenseNode,
            MockCVSenseNode,
            MockDMXOutputNode,
        )
        nodes["audio_sense"] = MockAudioSenseNode()
        nodes["midi_sense"] = MockMidiSenseNode()
        nodes["cv_sense"] = MockCVSenseNode()
        nodes["dmx_output"] = MockDMXOutputNode()
    else:
        nodes["audio_sense"] = AudioSenseNode(settings.audio)
        nodes["midi_sense"] = MidiSenseNode(settings.midi)
        nodes["cv_sense"] = CVSenseNode(settings.cv)
        nodes["dmx_output"] = DMXOutputNode(settings.dmx)

    # Analysis nodes (always real)
    nodes["feature_extract"] = FeatureExtractNode()
    nodes["beat_track"] = BeatTrackNode(settings.beat_tracking)
    nodes["structure_detect"] = StructureDetectNode(settings.structure_detection)
    nodes["fusion"] = FusionNode()
    nodes["scene_select"] = SceneSelectNode(settings.scene)

    # Fixture control nodes
    nodes["laser_control"] = LaserControlNode(settings.fixtures, settings.safety.laser)
    nodes["moving_head_control"] = MovingHeadControlNode(
        settings.fixtures, settings.safety.moving_head
    )
    nodes["panel_control"] = PanelControlNode(settings.fixtures)

    # Safety node
    nodes["safety_interlock"] = SafetyInterlockNode(settings.safety, settings.fixtures)

    # Build graph
    graph = StateGraph(PhotonicState)

    # Add all nodes
    for name, node in nodes.items():
        graph.add_node(name, node)

    # Define edges
    # Entry point: audio capture
    graph.set_entry_point("audio_sense")

    # Parallel sensor acquisition
    # Audio path
    graph.add_edge("audio_sense", "feature_extract")
    graph.add_edge("feature_extract", "beat_track")
    graph.add_edge("beat_track", "structure_detect")
    graph.add_edge("structure_detect", "fusion")

    # MIDI path (parallel to audio)
    graph.add_edge("audio_sense", "midi_sense")
    graph.add_edge("midi_sense", "fusion")

    # CV path (parallel to audio)
    graph.add_edge("audio_sense", "cv_sense")
    graph.add_edge("cv_sense", "fusion")

    # Scene selection after fusion
    graph.add_edge("fusion", "scene_select")

    # Parallel fixture control
    graph.add_edge("scene_select", "laser_control")
    graph.add_edge("scene_select", "moving_head_control")
    graph.add_edge("scene_select", "panel_control")

    # Converge to DMX output
    graph.add_edge("laser_control", "dmx_output")
    graph.add_edge("moving_head_control", "dmx_output")
    graph.add_edge("panel_control", "dmx_output")

    # Safety check
    graph.add_edge("dmx_output", "safety_interlock")

    # Loop back for continuous operation
    # Note: In practice, we use run_loop() which handles the iteration
    graph.add_edge("safety_interlock", END)

    # Compile
    compiled = graph.compile()

    return PhotonicGraph(compiled, settings, nodes)


def build_minimal_graph(settings: Optional[Settings] = None) -> PhotonicGraph:
    """
    Build a minimal graph for testing DMX output only.

    Useful for fixture calibration and basic testing without
    full audio analysis.
    """
    if settings is None:
        settings = Settings()

    from photonic_synesthesia.graph.nodes.mocks import MockAudioSenseNode

    nodes = {
        "audio_sense": MockAudioSenseNode(),
        "dmx_output": DMXOutputNode(settings.dmx),
        "safety_interlock": SafetyInterlockNode(settings.safety, settings.fixtures),
    }

    graph = StateGraph(PhotonicState)

    for name, node in nodes.items():
        graph.add_node(name, node)

    graph.set_entry_point("audio_sense")
    graph.add_edge("audio_sense", "dmx_output")
    graph.add_edge("dmx_output", "safety_interlock")
    graph.add_edge("safety_interlock", END)

    compiled = graph.compile()
    return PhotonicGraph(compiled, settings, nodes)
