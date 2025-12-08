"""
Custom Exceptions for Photonic Synesthesia.

Provides a hierarchy of exceptions for different system components,
enabling targeted error handling and graceful degradation.
"""

from __future__ import annotations

from typing import Optional


class PhotonicError(Exception):
    """Base exception for all Photonic Synesthesia errors."""

    def __init__(self, message: str, recoverable: bool = True):
        super().__init__(message)
        self.message = message
        self.recoverable = recoverable


# =============================================================================
# DMX Errors
# =============================================================================


class DMXError(PhotonicError):
    """Base exception for DMX-related errors."""
    pass


class DMXConnectionError(DMXError):
    """Failed to connect to DMX interface."""

    def __init__(self, interface: str, reason: str):
        super().__init__(
            f"Failed to connect to DMX interface '{interface}': {reason}",
            recoverable=False
        )
        self.interface = interface
        self.reason = reason


class DMXTransmissionError(DMXError):
    """Error during DMX frame transmission."""

    def __init__(self, reason: str):
        super().__init__(f"DMX transmission error: {reason}", recoverable=True)


class DMXAddressError(DMXError):
    """Invalid DMX address or channel."""

    def __init__(self, address: int, reason: str):
        super().__init__(f"Invalid DMX address {address}: {reason}", recoverable=True)
        self.address = address


# =============================================================================
# Audio Errors
# =============================================================================


class AudioError(PhotonicError):
    """Base exception for audio-related errors."""
    pass


class AudioCaptureError(AudioError):
    """Failed to capture audio from input device."""

    def __init__(self, device: Optional[str], reason: str):
        device_str = device or "default device"
        super().__init__(
            f"Audio capture failed on {device_str}: {reason}",
            recoverable=True
        )
        self.device = device
        self.reason = reason


class AudioDeviceNotFoundError(AudioError):
    """Requested audio device not found."""

    def __init__(self, device: str):
        super().__init__(f"Audio device not found: {device}", recoverable=False)
        self.device = device


class AudioAnalysisError(AudioError):
    """Error during audio feature extraction."""

    def __init__(self, stage: str, reason: str):
        super().__init__(f"Audio analysis error in {stage}: {reason}", recoverable=True)
        self.stage = stage


# =============================================================================
# MIDI Errors
# =============================================================================


class MidiError(PhotonicError):
    """Base exception for MIDI-related errors."""
    pass


class MidiPortNotFoundError(MidiError):
    """MIDI port not found."""

    def __init__(self, port_name: str, available_ports: list[str]):
        ports_str = ", ".join(available_ports) if available_ports else "none"
        super().__init__(
            f"MIDI port '{port_name}' not found. Available: {ports_str}",
            recoverable=False
        )
        self.port_name = port_name
        self.available_ports = available_ports


class MidiConnectionError(MidiError):
    """Failed to connect to MIDI port."""

    def __init__(self, port_name: str, reason: str):
        super().__init__(f"Failed to connect to MIDI port '{port_name}': {reason}")
        self.port_name = port_name


# =============================================================================
# Computer Vision Errors
# =============================================================================


class CVError(PhotonicError):
    """Base exception for computer vision errors."""
    pass


class ScreenCaptureError(CVError):
    """Failed to capture screen region."""

    def __init__(self, region: tuple, reason: str):
        super().__init__(f"Screen capture failed for region {region}: {reason}")
        self.region = region


class OCRError(CVError):
    """Failed to recognize text/digits in image."""

    def __init__(self, target: str, reason: str):
        super().__init__(f"OCR failed for {target}: {reason}", recoverable=True)
        self.target = target


# =============================================================================
# Safety Errors
# =============================================================================


class SafetyError(PhotonicError):
    """Base exception for safety system errors."""
    pass


class SafetyInterlockError(SafetyError):
    """Safety interlock triggered - requires immediate response."""

    def __init__(self, interlock: str, reason: str, action_taken: str):
        super().__init__(
            f"Safety interlock '{interlock}' triggered: {reason}. Action: {action_taken}",
            recoverable=False
        )
        self.interlock = interlock
        self.action_taken = action_taken


class EmergencyStopError(SafetyError):
    """Emergency stop activated."""

    def __init__(self, source: str):
        super().__init__(f"Emergency stop activated by {source}", recoverable=False)
        self.source = source


class HeartbeatTimeoutError(SafetyError):
    """System heartbeat timeout - analysis may have hung."""

    def __init__(self, timeout_s: float, last_heartbeat: float):
        super().__init__(
            f"Heartbeat timeout after {timeout_s}s (last: {last_heartbeat})",
            recoverable=True
        )
        self.timeout_s = timeout_s
        self.last_heartbeat = last_heartbeat


# =============================================================================
# Configuration Errors
# =============================================================================


class ConfigError(PhotonicError):
    """Base exception for configuration errors."""
    pass


class FixtureProfileError(ConfigError):
    """Invalid or missing fixture profile."""

    def __init__(self, profile: str, reason: str):
        super().__init__(f"Fixture profile error '{profile}': {reason}")
        self.profile = profile


class SceneError(ConfigError):
    """Invalid or missing scene definition."""

    def __init__(self, scene: str, reason: str):
        super().__init__(f"Scene error '{scene}': {reason}")
        self.scene = scene


# =============================================================================
# Graph Errors
# =============================================================================


class GraphError(PhotonicError):
    """Base exception for LangGraph-related errors."""
    pass


class NodeExecutionError(GraphError):
    """Error during graph node execution."""

    def __init__(self, node: str, reason: str, state_snapshot: Optional[dict] = None):
        super().__init__(f"Node '{node}' execution failed: {reason}")
        self.node = node
        self.state_snapshot = state_snapshot


class EdgeConditionError(GraphError):
    """Error evaluating edge condition."""

    def __init__(self, edge: str, reason: str):
        super().__init__(f"Edge condition '{edge}' failed: {reason}")
        self.edge = edge
