"""Core system components for Photonic Synesthesia."""

from photonic_synesthesia.core.state import PhotonicState, MusicStructure, FixtureCommand
from photonic_synesthesia.core.config import Settings
from photonic_synesthesia.core.exceptions import (
    PhotonicError,
    DMXError,
    AudioCaptureError,
    SafetyInterlockError,
)

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
