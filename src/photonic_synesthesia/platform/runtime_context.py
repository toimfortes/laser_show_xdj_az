"""Shared runtime context for process-local control-plane services."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock

from photonic_synesthesia.platform.state_service import ControlPlaneStateService

_LOCK = Lock()
_SHARED_CONTROL_PLANE_SERVICE: ControlPlaneStateService | None = None
_SHARED_PLAYBACK_CONTEXT: PlaybackContext | None = None


@dataclass(slots=True)
class PlaybackContext:
    """Process-local playback metadata exposed to the web control plane."""

    file_path: str
    file_name: str
    duration_seconds: float
    waveform: list[float] = field(default_factory=list)


def get_shared_control_plane_service(create: bool = False) -> ControlPlaneStateService | None:
    """Return the shared process-local control-plane service."""
    global _SHARED_CONTROL_PLANE_SERVICE
    with _LOCK:
        if _SHARED_CONTROL_PLANE_SERVICE is None and create:
            _SHARED_CONTROL_PLANE_SERVICE = ControlPlaneStateService()
        return _SHARED_CONTROL_PLANE_SERVICE


def set_shared_control_plane_service(service: ControlPlaneStateService) -> ControlPlaneStateService:
    """Install the shared process-local control-plane service."""
    global _SHARED_CONTROL_PLANE_SERVICE
    with _LOCK:
        _SHARED_CONTROL_PLANE_SERVICE = service
        return service


def clear_shared_control_plane_service() -> None:
    """Clear the shared process-local control-plane service."""
    global _SHARED_CONTROL_PLANE_SERVICE
    with _LOCK:
        _SHARED_CONTROL_PLANE_SERVICE = None


def get_shared_playback_context() -> PlaybackContext | None:
    """Return the shared process-local playback metadata."""
    with _LOCK:
        return _SHARED_PLAYBACK_CONTEXT


def set_shared_playback_context(context: PlaybackContext) -> PlaybackContext:
    """Install shared process-local playback metadata."""
    global _SHARED_PLAYBACK_CONTEXT
    with _LOCK:
        _SHARED_PLAYBACK_CONTEXT = context
        return context


def clear_shared_playback_context() -> None:
    """Clear shared playback metadata."""
    global _SHARED_PLAYBACK_CONTEXT
    with _LOCK:
        _SHARED_PLAYBACK_CONTEXT = None
