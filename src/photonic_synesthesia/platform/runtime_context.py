"""Shared runtime context for process-local control-plane services."""

from __future__ import annotations

from threading import Lock

from photonic_synesthesia.platform.state_service import ControlPlaneStateService

_LOCK = Lock()
_SHARED_CONTROL_PLANE_SERVICE: ControlPlaneStateService | None = None


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
