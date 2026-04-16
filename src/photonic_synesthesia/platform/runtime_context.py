"""Shared runtime context for process-local control-plane services."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any
from uuid import uuid4

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
    session_id: str = field(default_factory=lambda: uuid4().hex)
    waveform: list[float] = field(default_factory=list)
    playhead_seconds: float = 0.0
    playing: bool = False
    finished: bool = False
    realtime: bool = True
    speed: float = 1.0
    server_time: float = 0.0
    transport_revision: int = 0
    _lock: Lock = field(default_factory=Lock, repr=False)

    def update_transport(
        self,
        *,
        playhead_seconds: float,
        playing: bool,
        finished: bool,
        realtime: bool,
        speed: float,
    ) -> None:
        """Update live transport state for browser sync."""
        with self._lock:
            self.playhead_seconds = max(0.0, min(playhead_seconds, self.duration_seconds))
            self.playing = playing
            self.finished = finished
            self.realtime = realtime
            self.speed = max(0.01, speed)
            self.server_time = time.time()
            self.transport_revision += 1

    def snapshot(self) -> dict[str, Any]:
        """Return a thread-safe snapshot for API responses."""
        with self._lock:
            return {
                "available": True,
                "session_id": self.session_id,
                "file_name": self.file_name,
                "duration_seconds": self.duration_seconds,
                "audio_url": f"/api/mock/playback/audio?session={self.session_id}",
                "waveform": list(self.waveform),
                "playhead_seconds": self.playhead_seconds,
                "playing": self.playing,
                "finished": self.finished,
                "realtime": self.realtime,
                "speed": self.speed,
                "server_time": self.server_time,
                "transport_revision": self.transport_revision,
            }


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
