"""Shared runtime context for process-local control-plane services."""

from __future__ import annotations

import copy
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from photonic_synesthesia.platform.runtime_context_normalization import (
    clamp as _clamp,
)
from photonic_synesthesia.platform.runtime_context_normalization import (
    normalize_metadata_source as _normalize_metadata_source,
)
from photonic_synesthesia.platform.runtime_context_normalization import (
    normalize_operator_intent as _normalize_operator_intent,
)
from photonic_synesthesia.platform.runtime_context_normalization import (
    normalize_operator_scope as _normalize_operator_scope,
)
from photonic_synesthesia.platform.runtime_context_normalization import (
    normalize_operator_target as _normalize_operator_target,
)
from photonic_synesthesia.platform.runtime_context_normalization import (
    normalize_selection_mode as _normalize_selection_mode,
)
from photonic_synesthesia.platform.runtime_context_normalization import (
    normalize_selection_variance as _normalize_selection_variance,
)
from photonic_synesthesia.platform.runtime_context_normalization import (
    normalize_venue_mode as _normalize_venue_mode,
)
from photonic_synesthesia.platform.runtime_context_operator_intents import (
    apply_operator_intent_to_section as _apply_operator_intent_to_section,
)
from photonic_synesthesia.platform.runtime_context_operator_intents import (
    intent_expired as _intent_expired,
)
from photonic_synesthesia.platform.runtime_context_playback_scope import (
    section_ids_for_scope as _section_ids_for_scope,
)
from photonic_synesthesia.platform.runtime_context_section_mutations import (
    apply_nested_change as _apply_nested_change,
)
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
    selection_mode: str = "procedural"
    selection_variance: float = 0.0
    venue_mode: str = "small_room_50_100"
    metadata_confidence: dict[str, Any] = field(default_factory=dict)
    operator_intents: list[dict[str, Any]] = field(default_factory=list)
    metadata_source: str = "file_playback"
    metadata_bound_at: float = 0.0
    show_source: str = "generated"
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
    _regenerate_callback: Callable[[str, float], list[dict[str, Any]]] | None = field(default=None, repr=False)
    _metadata_bind_callback: Callable[[dict[str, Any]], dict[str, Any]] | None = field(default=None, repr=False)
    _base_show_sections: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def __post_init__(self) -> None:
        self.selection_mode = _normalize_selection_mode(self.selection_mode)
        self.selection_variance = _normalize_selection_variance(self.selection_variance)
        self.venue_mode = _normalize_venue_mode(self.venue_mode)
        self.metadata_source = _normalize_metadata_source(self.metadata_source)
        self._base_show_sections = copy.deepcopy(self.show_sections)
        with self._lock:
            self._refresh_operator_intents_locked()

    def _refresh_operator_intents_locked(self) -> None:
        active_intents = [
            copy.deepcopy(intent_payload)
            for intent_payload in self.operator_intents
            if not _intent_expired(intent_payload, self._base_show_sections, self.playhead_seconds, self.duration_seconds)
        ]
        sections = copy.deepcopy(self._base_show_sections)
        for intent_payload in active_intents:
            target_ids = {str(item) for item in list(intent_payload.get("target_ids") or [])}
            if not target_ids:
                target_ids = _section_ids_for_scope(
                    sections,
                    float(intent_payload.get("applied_playhead_seconds") or self.playhead_seconds),
                    _normalize_operator_scope(intent_payload.get("scope")),
                )
                intent_payload["target_ids"] = sorted(target_ids)
            updated_sections: list[dict[str, Any]] = []
            for section in sections:
                section_id = str(section.get("id") or "")
                if section_id in target_ids:
                    updated_sections.append(
                        _apply_operator_intent_to_section(
                            section,
                            intent=_normalize_operator_intent(intent_payload.get("intent")),
                            target=_normalize_operator_target(intent_payload.get("target")),
                            amount=_clamp(float(intent_payload.get("amount") or 0.0), 0.0, 1.0),
                            duration_seconds=self.duration_seconds,
                        )
                    )
                else:
                    updated_sections.append(copy.deepcopy(section))
            sections = updated_sections
        self.operator_intents = active_intents
        self.show_sections = sections

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
            self._refresh_operator_intents_locked()
            self.server_time = time.time()
            self.transport_revision += 1

    def snapshot(self) -> dict[str, Any]:
        """Return a thread-safe snapshot for API responses."""
        with self._lock:
            self._refresh_operator_intents_locked()
            export_available = bool(self.ilda_export_path and Path(self.ilda_export_path).is_file())
            audio_available = bool(self.file_path and Path(self.file_path).is_file())
            seekable = self._seek_callback is not None
            return {
                "available": True,
                "session_id": self.session_id,
                "file_name": self.file_name,
                "track_title": self.track_title or self.file_name,
                "track_artist": self.track_artist,
                "track_key": self.track_key,
                "duration_seconds": self.duration_seconds,
                "audio_url": (
                    f"/api/mock/playback/audio?session={self.session_id}"
                    if audio_available
                    else None
                ),
                "audio_available": audio_available,
                "seekable": seekable,
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
                "show_sections": copy.deepcopy(self.show_sections),
                "selection_mode": _normalize_selection_mode(self.selection_mode),
                "selection_variance": _normalize_selection_variance(self.selection_variance),
                "venue_mode": _normalize_venue_mode(self.venue_mode),
                "metadata_confidence": copy.deepcopy(self.metadata_confidence),
                "operator_intents": copy.deepcopy(self.operator_intents),
                "metadata_source": _normalize_metadata_source(self.metadata_source),
                "metadata_bound_at": self.metadata_bound_at,
                "show_source": str(self.show_source or "generated"),
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
                updated = copy.deepcopy(self._base_show_sections[index] if index < len(self._base_show_sections) else section)
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
                        _apply_nested_change(updated, key, value)
                if index < len(self._base_show_sections):
                    self._base_show_sections[index] = copy.deepcopy(updated)
                else:
                    self._base_show_sections.append(copy.deepcopy(updated))
                self._refresh_operator_intents_locked()
                save_payload = self._show_plan_payload_locked()
                updated_section = copy.deepcopy(self.show_sections[index])
                break
        if save_payload is not None and updated_section is not None:
            self._persist_show_plan(save_payload)
        return updated_section

    def _show_plan_payload_locked(self) -> dict[str, Any]:
        return {
            "track_key": self.track_key,
            "track_title": self.track_title,
            "track_artist": self.track_artist,
            "file_name": self.file_name,
            "duration_seconds": self.duration_seconds,
            "structure_markers": [dict(marker) for marker in self.structure_markers],
            "show_sections": copy.deepcopy(self.show_sections),
            "selection_mode": _normalize_selection_mode(self.selection_mode),
            "selection_variance": _normalize_selection_variance(self.selection_variance),
            "venue_mode": _normalize_venue_mode(self.venue_mode),
            "metadata_confidence": copy.deepcopy(self.metadata_confidence),
            "operator_intents": copy.deepcopy(self.operator_intents),
            "metadata_source": _normalize_metadata_source(self.metadata_source),
        }

    def _persist_show_plan(self, payload: dict[str, Any]) -> None:
        callback = self._save_callback
        if callback is None:
            return
        result = callback(payload)
        if result:
            with self._lock:
                self.show_plan_path = str(result)
                self.show_source = "show_plan"

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

    def _regenerate_selection(
        self,
        *,
        selection_mode: str | None = None,
        selection_variance: float | None = None,
    ) -> dict[str, Any]:
        regenerate_callback = self._regenerate_callback
        if regenerate_callback is None:
            raise RuntimeError("Playback selection mode is not configurable")

        with self._lock:
            current_mode = _normalize_selection_mode(self.selection_mode)
            current_variance = _normalize_selection_variance(self.selection_variance)
        normalized_mode = _normalize_selection_mode(selection_mode if selection_mode is not None else current_mode)
        normalized_variance = _normalize_selection_variance(
            selection_variance if selection_variance is not None else current_variance
        )
        if normalized_mode == current_mode and normalized_variance == current_variance:
            return self.snapshot()

        regenerated_sections = regenerate_callback(normalized_mode, normalized_variance)
        if not isinstance(regenerated_sections, list):
            raise RuntimeError("Playback regeneration did not return show sections")

        with self._lock:
            self.selection_mode = normalized_mode
            self.selection_variance = normalized_variance
            self._base_show_sections = copy.deepcopy(regenerated_sections)
            self._refresh_operator_intents_locked()
            payload = self._show_plan_payload_locked()
        self._persist_show_plan(payload)
        return self.snapshot()

    def set_selection_mode(self, selection_mode: str) -> dict[str, Any]:
        """Regenerate the current show plan using a different selection mode."""
        return self._regenerate_selection(selection_mode=selection_mode)

    def set_selection_variance(self, selection_variance: float) -> dict[str, Any]:
        """Regenerate the current show plan using a different exploration setting."""
        return self._regenerate_selection(selection_variance=selection_variance)

    def apply_operator_intent(
        self,
        *,
        intent: str,
        scope: str = "track",
        target: str = "all",
        amount: float = 0.25,
        expires_at: str = "",
    ) -> dict[str, Any]:
        """Apply a typed operator steering intent to the current playback plan."""
        normalized_intent = _normalize_operator_intent(intent)
        if not normalized_intent:
            raise RuntimeError("Unsupported operator intent")
        normalized_scope = _normalize_operator_scope(scope)
        normalized_target = _normalize_operator_target(target)
        normalized_amount = round(_clamp(float(amount), 0.0, 1.0), 3)

        with self._lock:
            target_ids = _section_ids_for_scope(self._base_show_sections, self.playhead_seconds, normalized_scope)
            intent_payload = {
                "intent": normalized_intent,
                "scope": normalized_scope,
                "target": normalized_target,
                "amount": normalized_amount,
                "expires_at": str(expires_at or ""),
                "target_ids": sorted(target_ids),
                "applied_playhead_seconds": round(self.playhead_seconds, 3),
                "applied_at": time.time(),
            }
            self.operator_intents.append(intent_payload)
            self._refresh_operator_intents_locked()
            payload = self._show_plan_payload_locked()
        self._persist_show_plan(payload)
        return self.snapshot()

    def bind_track_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """Resolve live track metadata into playback metadata and a show plan."""
        callback = self._metadata_bind_callback
        if callback is None:
            raise RuntimeError("Playback metadata binding is not configured")

        binding = callback(dict(metadata))
        if not isinstance(binding, dict):
            raise RuntimeError("Playback metadata binding did not return a payload")

        with self._lock:
            self.track_title = str(binding.get("track_title") or self.track_title or self.file_name)
            self.track_artist = str(binding.get("track_artist") or self.track_artist)
            self.track_key = str(binding.get("track_key") or self.track_key)
            self.file_name = str(binding.get("file_name") or self.file_name or self.track_title)
            self.structure_markers = [
                dict(marker) for marker in binding.get("structure_markers", self.structure_markers)
            ]
            self._base_show_sections = copy.deepcopy(binding.get("show_sections", self.show_sections))
            self.selection_mode = _normalize_selection_mode(
                binding.get("selection_mode", self.selection_mode)
            )
            self.selection_variance = _normalize_selection_variance(
                binding.get("selection_variance", self.selection_variance)
            )
            self.venue_mode = _normalize_venue_mode(
                binding.get("venue_mode", self.venue_mode)
            )
            confidence = binding.get("metadata_confidence", self.metadata_confidence)
            self.metadata_confidence = copy.deepcopy(confidence if isinstance(confidence, dict) else {})
            intents = binding.get("operator_intents", self.operator_intents)
            self.operator_intents = copy.deepcopy(intents if isinstance(intents, list) else [])
            self.metadata_source = _normalize_metadata_source(
                binding.get("metadata_source", metadata.get("metadata_source", self.metadata_source))
            )
            self.metadata_bound_at = time.time()
            self.show_source = str(binding.get("show_source") or self.show_source or "generated")

            if binding.get("duration_seconds") is not None:
                try:
                    self.duration_seconds = max(0.0, float(binding["duration_seconds"]))
                except (TypeError, ValueError):
                    pass
            if binding.get("playhead_seconds") is not None:
                try:
                    self.playhead_seconds = max(
                        0.0,
                        min(float(binding["playhead_seconds"]), self.duration_seconds),
                    )
                except (TypeError, ValueError):
                    pass
            if binding.get("playing") is not None:
                self.playing = bool(binding["playing"])
            if binding.get("finished") is not None:
                self.finished = bool(binding["finished"])
            if binding.get("realtime") is not None:
                self.realtime = bool(binding["realtime"])
            if binding.get("speed") is not None:
                try:
                    self.speed = max(0.01, float(binding["speed"]))
                except (TypeError, ValueError):
                    pass
            self.server_time = time.time()
            self._refresh_operator_intents_locked()
            self.transport_revision += 1
            payload = self._show_plan_payload_locked()

        self._persist_show_plan(payload)
        return self.snapshot()


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
