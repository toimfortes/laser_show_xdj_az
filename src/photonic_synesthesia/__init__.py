"""
Photonic Synesthesia: AI-Driven Laser Show Controller for XDJ-AZ

An autonomous lighting control system that uses LangGraph for orchestration,
combining real-time audio analysis, MIDI telemetry, and computer vision
to create structure-aware, music-reactive light shows.
"""

__version__ = "0.1.0"
__author__ = "Photonic Synesthesia Team"

from photonic_synesthesia.core.config import Settings
from photonic_synesthesia.core.state import MusicStructure, PhotonicState

__all__ = [
    "PhotonicState",
    "MusicStructure",
    "Settings",
    "__version__",
]
