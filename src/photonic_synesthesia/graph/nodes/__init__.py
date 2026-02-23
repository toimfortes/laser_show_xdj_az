"""Lazy node exports for graph construction."""

from __future__ import annotations

import importlib
from typing import Any

_NODE_IMPORTS = {
    "AudioSenseNode": ("photonic_synesthesia.graph.nodes.audio_sense", "AudioSenseNode"),
    "FeatureExtractNode": (
        "photonic_synesthesia.graph.nodes.feature_extract",
        "FeatureExtractNode",
    ),
    "BeatTrackNode": ("photonic_synesthesia.graph.nodes.beat_track", "BeatTrackNode"),
    "StructureDetectNode": (
        "photonic_synesthesia.graph.nodes.structure_detect",
        "StructureDetectNode",
    ),
    "MidiSenseNode": ("photonic_synesthesia.graph.nodes.midi_sense", "MidiSenseNode"),
    "CVSenseNode": ("photonic_synesthesia.graph.nodes.cv_sense", "CVSenseNode"),
    "FusionNode": ("photonic_synesthesia.graph.nodes.fusion", "FusionNode"),
    "DirectorIntentNode": (
        "photonic_synesthesia.graph.nodes.director_intent",
        "DirectorIntentNode",
    ),
    "SceneSelectNode": ("photonic_synesthesia.graph.nodes.scene_select", "SceneSelectNode"),
    "LaserControlNode": ("photonic_synesthesia.graph.nodes.fixture_control", "LaserControlNode"),
    "MovingHeadControlNode": (
        "photonic_synesthesia.graph.nodes.fixture_control",
        "MovingHeadControlNode",
    ),
    "PanelControlNode": ("photonic_synesthesia.graph.nodes.fixture_control", "PanelControlNode"),
    "InterpreterNode": ("photonic_synesthesia.graph.nodes.interpreter", "InterpreterNode"),
    "DMXOutputNode": ("photonic_synesthesia.graph.nodes.dmx_output", "DMXOutputNode"),
    "SafetyInterlockNode": (
        "photonic_synesthesia.graph.nodes.safety_interlock",
        "SafetyInterlockNode",
    ),
}


def __getattr__(name: str) -> Any:
    if name not in _NODE_IMPORTS:
        raise AttributeError(name)
    module_name, symbol = _NODE_IMPORTS[name]
    module = importlib.import_module(module_name)
    return getattr(module, symbol)


__all__ = list(_NODE_IMPORTS)
