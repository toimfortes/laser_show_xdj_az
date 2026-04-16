"""Shared runtime context for process-local control-plane services."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
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
    track_title: str = ""
    track_artist: str = ""
    track_key: str = ""
    session_id: str = field(default_factory=lambda: uuid4().hex)
    waveform: list[float] = field(default_factory=list)
    structure_markers: list[dict[str, Any]] = field(default_factory=list)
    show_sections: list[dict[str, Any]] = field(default_factory=list)
    show_plan_path: str = ""
    ilda_transport_type: str = "memory"
    ilda_export_path: str = ""
    hardware_warnings: list[str] = field(default_factory=list)
    playhead_seconds: float = 0.0
    playing: bool = False
    finished: bool = False
    realtime: bool = True
    speed: float = 1.0
    server_time: float = 0.0
    transport_revision: int = 0
    _seek_callback: Callable[[float], float] | None = field(default=None, repr=False)
    _save_callback: Callable[[dict[str, Any]], str | None] | None = field(default=None, repr=False)
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
            export_available = bool(self.ilda_export_path and Path(self.ilda_export_path).is_file())
            return {
                "available": True,
                "session_id": self.session_id,
                "file_name": self.file_name,
                "track_title": self.track_title or self.file_name,
                "track_artist": self.track_artist,
                "track_key": self.track_key,
                "duration_seconds": self.duration_seconds,
                "audio_url": f"/api/mock/playback/audio?session={self.session_id}",
                "show_plan_path": self.show_plan_path,
                "ilda_transport_type": self.ilda_transport_type,
                "ilda_export_path": self.ilda_export_path,
                "ilda_export_available": export_available,
                "hardware_warnings": list(self.hardware_warnings),
                "ilda_export_url": (
                    f"/api/mock/playback/ilda-export?session={self.session_id}"
                    if export_available
                    else None
                ),
                "waveform": list(self.waveform),
                "structure_markers": [dict(marker) for marker in self.structure_markers],
                "show_sections": [dict(section) for section in self.show_sections],
                "playhead_seconds": self.playhead_seconds,
                "playing": self.playing,
                "finished": self.finished,
                "realtime": self.realtime,
                "speed": self.speed,
                "server_time": self.server_time,
                "transport_revision": self.transport_revision,
            }

    def update_show_section(self, section_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        """Update one editable show section in-place."""
        save_payload: dict[str, Any] | None = None
        updated_section: dict[str, Any] | None = None
        with self._lock:
            for index, section in enumerate(self.show_sections):
                if str(section.get("id")) != section_id:
                    continue
                updated = dict(section)
                for key, value in changes.items():
                    if key in {
                        "scene_id",
                        "fixture_mode",
                        "laser_pattern",
                        "mover_pattern",
                        "wash_pattern",
                        "led_pattern",
                    }:
                        updated[key] = str(value)
                    elif key in {"laser_enabled", "movers_enabled", "washes_enabled", "leds_enabled"}:
                        updated[key] = bool(value)
                    elif key in {"intensity_multiplier", "motion_multiplier", "strobe_level"}:
                        try:
                            updated[key] = float(value)
                        except (TypeError, ValueError):
                            continue
                    elif key == "label":
                        updated[key] = str(value)
                    elif "." in key:
                        self._apply_nested_change(updated, key, value)
                self.show_sections[index] = updated
                save_payload = self._show_plan_payload_locked()
                updated_section = dict(updated)
                break
        if save_payload is not None and updated_section is not None:
            self._persist_show_plan(save_payload)
        return updated_section

    @staticmethod
    def _apply_nested_change(section: dict[str, Any], dotted_key: str, value: Any) -> None:
        parts = dotted_key.split(".")
        target: Any = section
        for index, part in enumerate(parts[:-1]):
            next_part = parts[index + 1]
            expect_list = next_part.isdigit()
            if isinstance(target, list):
                if not part.isdigit():
                    return
                item_index = int(part)
                while len(target) <= item_index:
                    target.append([] if expect_list else {})
                current = target[item_index]
                if expect_list and not isinstance(current, list):
                    current = []
                    target[item_index] = current
                elif not expect_list and not isinstance(current, dict):
                    current = {}
                    target[item_index] = current
                target = current
                continue

            if not isinstance(target, dict):
                return

            current = target.get(part)
            if expect_list:
                if not isinstance(current, list):
                    current = []
                    target[part] = current
            else:
                if not isinstance(current, dict):
                    current = {}
                    target[part] = current
            target = current
        leaf = parts[-1]
        if leaf in {
            "content_family",
            "geometry_family",
            "color_mode",
            "target_bias",
            "target_strategy",
            "blanking_strategy",
            "color_strategy",
            "transition_role",
            "label",
            "intensity_curve",
            "pattern",
            "zone_policy",
            "phrase_role",
            "id",
        }:
            if isinstance(target, dict):
                target[leaf] = str(value)
        elif leaf in {"mirror"}:
            if isinstance(target, dict):
                target[leaf] = bool(value)
        elif leaf in {
            "x_amplitude",
            "y_amplitude",
            "rotation_rate",
            "sweep_density",
            "color_cycle_rate",
            "white_accent",
            "crowd_bias",
            "ceiling_bias",
            "launch_intensity",
            "sustain_intensity",
            "release_intensity",
            "sustain_motion",
            "density",
            "motion",
            "emphasis",
        }:
            try:
                if isinstance(target, dict):
                    target[leaf] = float(value)
            except (TypeError, ValueError):
                return
        elif leaf in {"launch_bars", "sustain_bars", "release_bars", "normalize_after_bars"}:
            try:
                if isinstance(target, dict):
                    target[leaf] = int(value)
            except (TypeError, ValueError):
                return
        elif leaf == "variation_plan":
            if not isinstance(target, dict):
                return
            if isinstance(value, list):
                target[leaf] = [str(item) for item in value]
            else:
                target[leaf] = [line.strip() for line in str(value).splitlines() if line.strip()]

    def _show_plan_payload_locked(self) -> dict[str, Any]:
        return {
            "track_key": self.track_key,
            "track_title": self.track_title,
            "track_artist": self.track_artist,
            "file_name": self.file_name,
            "duration_seconds": self.duration_seconds,
            "structure_markers": [dict(marker) for marker in self.structure_markers],
            "show_sections": [dict(section) for section in self.show_sections],
        }

    def _persist_show_plan(self, payload: dict[str, Any]) -> None:
        callback = self._save_callback
        if callback is None:
            return
        result = callback(payload)
        if result:
            with self._lock:
                self.show_plan_path = str(result)

    def persist_current_show_plan(self) -> str | None:
        """Persist the current show plan if a callback is configured."""
        with self._lock:
            payload = self._show_plan_payload_locked()
        self._persist_show_plan(payload)
        with self._lock:
            return self.show_plan_path or None

    def request_seek(self, position_seconds: float) -> float:
        """Seek the backing transport and refresh exported playhead state."""
        callback = self._seek_callback
        if callback is None:
            raise RuntimeError("Playback transport is not seekable")
        new_position = callback(position_seconds)
        with self._lock:
            self.playhead_seconds = max(0.0, min(float(new_position), self.duration_seconds))
            self.finished = self.playhead_seconds >= self.duration_seconds
            self.server_time = time.time()
            self.transport_revision += 1
            return self.playhead_seconds


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
