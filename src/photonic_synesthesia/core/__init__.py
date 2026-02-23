"""Core system components for Photonic Synesthesia."""

from photonic_synesthesia.core.config import Settings
from photonic_synesthesia.core.exceptions import (
    AudioCaptureError,
    DMXError,
    PhotonicError,
    SafetyInterlockError,
)
from photonic_synesthesia.core.state import FixtureCommand, MusicStructure, PhotonicState

__all__ = [
    "PhotonicState",
    "MusicStructure",
    "FixtureCommand",
    "Settings",
    "PhotonicError",
    "DMXError",
    "AudioCaptureError",
    "SafetyInterlockError",
]
