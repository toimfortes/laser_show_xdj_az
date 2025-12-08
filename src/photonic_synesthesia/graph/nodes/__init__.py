"""
Graph Node Implementations for Photonic Synesthesia.

Each node is a callable that takes a PhotonicState and returns
an updated PhotonicState. Nodes handle specific aspects of the
sensor-to-light pipeline.
"""

from photonic_synesthesia.graph.nodes.audio_sense import AudioSenseNode
from photonic_synesthesia.graph.nodes.feature_extract import FeatureExtractNode
from photonic_synesthesia.graph.nodes.beat_track import BeatTrackNode
from photonic_synesthesia.graph.nodes.structure_detect import StructureDetectNode
from photonic_synesthesia.graph.nodes.midi_sense import MidiSenseNode
from photonic_synesthesia.graph.nodes.cv_sense import CVSenseNode
from photonic_synesthesia.graph.nodes.fusion import FusionNode
from photonic_synesthesia.graph.nodes.scene_select import SceneSelectNode
from photonic_synesthesia.graph.nodes.fixture_control import (
    LaserControlNode,
    MovingHeadControlNode,
    PanelControlNode,
)
from photonic_synesthesia.graph.nodes.dmx_output import DMXOutputNode
from photonic_synesthesia.graph.nodes.safety_interlock import SafetyInterlockNode

__all__ = [
    "AudioSenseNode",
    "FeatureExtractNode",
    "BeatTrackNode",
    "StructureDetectNode",
    "MidiSenseNode",
    "CVSenseNode",
    "FusionNode",
    "SceneSelectNode",
    "LaserControlNode",
    "MovingHeadControlNode",
    "PanelControlNode",
    "DMXOutputNode",
    "SafetyInterlockNode",
]
