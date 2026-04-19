"""Shared runtime context for process-local control-plane services."""

from __future__ import annotations

import copy
import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from photonic_synesthesia.core.logging import get_logger
from photonic_synesthesia.platform.operator_workspace import build_operator_workspace_banks
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
from photonic_synesthesia.showplan.timeline_flags import derive_timeline_flags
from photonic_synesthesia.showplan.types import SAFETY_MODES

logger = get_logger(__name__)

_LOCK = Lock()
_SHARED_CONTROL_PLANE_SERVICE: ControlPlaneStateService | None = None
_SHARED_PLAYBACK_CONTEXT: PlaybackContext | None = None


def _compute_authored_hash(
    show_sections: list[dict[str, Any]],
    timeline_flags: list[dict[str, Any]],
    staged_look: dict[str, Any] | None,
) -> str:
    """Content hash of all authored fields. Drives `_authored_cache` validity.

    Cycle-2 panel NC-3 split: this hash gates the snapshot cache only;
    `_compute_flags_hash` separately gates `_timeline_flag_revision`.
    Operator-intent overlays are implicit in `show_sections` (the helper
    runs `_refresh_operator_intents_locked` before the hash is computed).
    """
    material = json.dumps(
        [show_sections, timeline_flags, staged_look],
        sort_keys=True,
        default=str,
    )
    return hashlib.sha1(material.encode("utf-8")).hexdigest()


def _compute_flags_hash(timeline_flags: list[dict[str, Any]]) -> str:
    """Content hash of `timeline_flags` only. Drives `_timeline_flag_revision`.

    Cycle-2 panel NC-3 split. Order-insensitive: a rebind that reshuffles
    persisted flags without content change does not bump the trigger ledger.
    """
    key = lambda f: (str(f.get("id") or ""), float(f.get("at_seconds", 0.0)))
    material = json.dumps(sorted(timeline_flags, key=key), sort_keys=True, default=str)
    return hashlib.sha1(material.encode("utf-8")).hexdigest()


def _flags_equivalent(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> bool:
    """Flags equal under id + kind + at_seconds + payload, order-insensitive."""
    key = lambda f: (str(f.get("id") or ""), str(f.get("kind") or ""), float(f.get("at_seconds", 0.0)))
    return sorted(a, key=key) == sorted(b, key=key)


def _resolve_active_scene_id(show_sections: list[dict[str, Any]], playhead: float) -> str:
    """Return the active section's id by playhead — for the live overlay."""
    if not show_sections:
        return ""
    for section in show_sections:
        start = float(section.get("start_seconds", 0.0))
        end = float(section.get("end_seconds", start))
        if start <= playhead < max(end, start + 1e-6):
            return str(section.get("id") or "")
    return str(show_sections[-1].get("id") or "")
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

    # --- Professional rollout authored fields (Task 1) ---
    timeline_flags: list[dict[str, Any]] = field(default_factory=list)
    staged_look: dict[str, Any] | None = None

    # Hash-derived revision counters (cycle-2 panel NC-3 split,
    # cycle-3 panel 3C-N3 init seeding).
    _authored_hash: str = field(default="", repr=False)
    _flags_hash: str = field(default="", repr=False)
    _timeline_flag_revision: int = 0

    # Authored-layer cache (cycle-2 panel UF-5/UF-7/UF-8 family).
    _authored_cache: dict[str, Any] | None = field(default=None, repr=False)
    _authored_cache_hash: str = field(default="", repr=False)

    # Persistence serializer lock (cycle-1 panel UF-15, cycle-2 panel NC-2:
    # caller-locked contract; held alongside `_lock` on every write path).
    _persistence_lock: Lock = field(default_factory=Lock, repr=False)

    # Hint for persisted timeline_flags ordering across rebind (cycle-2
    # panel NC-1: declared as a slots field). Cleared after each use.
    _persisted_timeline_flags_hint: list[dict[str, Any]] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.selection_mode = _normalize_selection_mode(self.selection_mode)
        self.selection_variance = _normalize_selection_variance(self.selection_variance)
        self.venue_mode = _normalize_venue_mode(self.venue_mode)
        self.metadata_source = _normalize_metadata_source(self.metadata_source)
        self._base_show_sections = copy.deepcopy(self.show_sections)
        with self._lock:
            self._refresh_operator_intents_locked()
            # Cycle-3 panel 3C-N3 fix: seed both hashes after the initial
            # intent refresh so the first mutation doesn't bump
            # `_timeline_flag_revision` spuriously (cycle-1 panel UF-9
            # regression). `self.show_sections` here reflects post-intent
            # state, which is what consumers see on first read.
            self._authored_hash = _compute_authored_hash(
                self.show_sections, self.timeline_flags, self.staged_look,
            )
            self._flags_hash = _compute_flags_hash(self.timeline_flags)

    def _refresh_operator_intents_locked(self) -> None:
        """Recompute show_sections from base + active intents, in place.

        Cycle-2 panel UF-4 fix: writes `self.show_sections[:]` instead of
        `self.show_sections = ...` so the list identity is preserved. The
        plan's "_replace_show_sections_locked is the only reassignment
        path" invariant relies on this.
        """
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
        # Index-wise in-place update preserves list identity.
        self.show_sections[:] = sections

    def _replace_show_sections_locked(self, show_sections: list[dict[str, Any]]) -> None:
        """Single authoritative writer for show_sections + derived state.

        Caller MUST hold `self._lock`. Callers preserving persisted-flag
        ordering set `self._persisted_timeline_flags_hint` BEFORE calling;
        the helper honors the hint only when its content matches the
        freshly-derived flags (cycle-1 panel UF-18). Bumps
        `_timeline_flag_revision` only when `_flags_hash` actually changes
        (cycle-2 panel NC-3 split).
        """
        self._base_show_sections = copy.deepcopy(show_sections)
        # Reassign list identity here — the only path outside __post_init__
        # that does so. After this point, _refresh_operator_intents_locked
        # mutates the list in place.
        self.show_sections = copy.deepcopy(show_sections)
        self._refresh_operator_intents_locked()
        derived_flags = derive_timeline_flags(self.show_sections)
        hint = self._persisted_timeline_flags_hint
        if hint is not None and _flags_equivalent(hint, derived_flags):
            self.timeline_flags = copy.deepcopy(hint)
        else:
            self.timeline_flags = derived_flags
        self._persisted_timeline_flags_hint = None
        self.server_time = time.time()
        new_authored = _compute_authored_hash(
            self.show_sections, self.timeline_flags, self.staged_look,
        )
        if new_authored != self._authored_hash:
            self._authored_hash = new_authored
        new_flags = _compute_flags_hash(self.timeline_flags)
        if new_flags != self._flags_hash:
            self._flags_hash = new_flags
            self._timeline_flag_revision += 1
        # Do NOT touch transport_revision — that counter is transport's.

    def _recompute_authored_hash_locked(self) -> None:
        """Recompute hashes after a mutation that bypasses the helper.

        Called from mutation paths that change `staged_look` directly
        (`set_staged_look`) or that trigger intent expiry without
        replacing sections (`update_transport`, `request_seek`). Caller
        MUST hold `self._lock`. Bumps `_timeline_flag_revision` only when
        `_flags_hash` changes (cycle-2 panel NC-3).
        """
        new_authored = _compute_authored_hash(
            self.show_sections, self.timeline_flags, self.staged_look,
        )
        if new_authored != self._authored_hash:
            self._authored_hash = new_authored
        new_flags = _compute_flags_hash(self.timeline_flags)
        if new_flags != self._flags_hash:
            self._flags_hash = new_flags
            self._timeline_flag_revision += 1

    def replace_show_sections(self, show_sections: list[dict[str, Any]]) -> dict[str, Any]:
        """Public writer. Joint-lock; persistence ordered with memory.

        Cycle-1 panel UF-15: lock ordering `_lock` → `_persistence_lock`.
        Cycle-2 panel NC-2: persistence helper is caller-locked
        (`_persist_show_plan_locked`).
        """
        with self._lock, self._persistence_lock:
            self._replace_show_sections_locked(show_sections)
            payload = self._show_plan_payload_locked()
            self._persist_show_plan_locked(payload)
        return self.snapshot()

    def update_transport(
        self,
        *,
        playhead_seconds: float,
        playing: bool,
        finished: bool,
        realtime: bool,
        speed: float,
    ) -> None:
        """Update live transport state for browser sync.

        Cycle-4 panel Codex-HIGH-1 fix: `_refresh_operator_intents_locked()`
        can change `self.show_sections` when an intent expires (playhead
        moved past TTL). The post-refresh `_recompute_authored_hash_locked()`
        catches that case so the authored cache and `_timeline_flag_revision`
        stay in sync. The hash recompute is a no-op when nothing changed
        (sub-100µs SHA1 over ~20KB of authored state).
        """
        with self._lock:
            self.playhead_seconds = max(0.0, min(playhead_seconds, self.duration_seconds))
            self.playing = playing
            self.finished = finished
            self.realtime = realtime
            self.speed = max(0.01, speed)
            self._refresh_operator_intents_locked()
            self._recompute_authored_hash_locked()
            self.server_time = time.time()
            self.transport_revision += 1

    def snapshot(self) -> dict[str, Any]:
        """PUBLIC snapshot — deep-copied so callers can freely mutate the result.

        Cycle-2 panel NC-8 + cycle-3 panel 3C-N2 split: this is the public
        API used by web-panel endpoints, tests, and UI consumers — they get
        a safe-to-mutate deep copy. The graph publisher uses
        `_snapshot_internal_locked` directly to avoid the public deep-copy
        cost on the hot path.
        """
        with self._lock:
            aliased = self._snapshot_internal_locked()
        return copy.deepcopy(aliased)

    def _snapshot_internal_locked(self) -> dict[str, Any]:
        """INTERNAL aliased snapshot — caller must hold `self._lock`.

        Cycle-3 panel 3C-N2 fix: returns a SUPERSET of shipped snapshot
        fields (transport/session/audio/ILDA/hardware/selection/metadata/
        operator_intents) PLUS new authored-cache fields PLUS per-call
        live overlay. Web-panel consumers continue to receive every field
        they already expected.
        """
        export_available = bool(self.ilda_export_path and Path(self.ilda_export_path).is_file())
        audio_available = bool(self.file_path and Path(self.file_path).is_file())
        seekable = self._seek_callback is not None
        base = {
            "available": True,
            "session_id": self.session_id,
            "file_name": self.file_name,
            "track_title": self.track_title or self.file_name,
            "track_artist": self.track_artist,
            "track_key": self.track_key,
            "duration_seconds": self.duration_seconds,
            "audio_url": (
                f"/api/mock/playback/audio?session={self.session_id}"
                if audio_available else None
            ),
            "audio_available": audio_available,
            "seekable": seekable,
            "show_plan_path": self.show_plan_path,
            "ilda_transport_type": self.ilda_transport_type,
            "ilda_export_path": self.ilda_export_path,
            "ilda_export_available": export_available,
            "ilda_export_url": (
                f"/api/mock/playback/ilda-export?session={self.session_id}"
                if export_available else None
            ),
            "hardware_warnings": list(self.hardware_warnings),
            "waveform": list(self.waveform),
            "structure_markers": [dict(marker) for marker in self.structure_markers],
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
        # Authored-cache layer keyed on `_authored_hash`. Aliased; the
        # `snapshot()` wrapper deep-copies. The graph publisher (which calls
        # this method directly) MUST also deep-copy before publishing.
        if self._authored_cache is not None and self._authored_cache_hash == self._authored_hash:
            authored_keys = self._authored_cache
        else:
            authored_keys = {
                "show_sections": copy.deepcopy(self.show_sections),
                "timeline_flags": copy.deepcopy(self.timeline_flags),
                "staged_look": copy.deepcopy(self.staged_look),
                "operator_workspace_banks": build_operator_workspace_banks(
                    sections=self.show_sections,
                    available_tags=sorted({t for s in self.show_sections for t in s.get("tags", [])}),
                    safety_modes=SAFETY_MODES,
                ),
                "timeline_flag_revision": self._timeline_flag_revision,
                "authored_hash": self._authored_hash,
            }
            self._authored_cache = authored_keys
            self._authored_cache_hash = self._authored_hash
        # Per-call live overlay (cycle-1 panel UF-7 — active_scene_id MUST
        # come from live playhead, not the cache).
        live = {
            "active_scene_id": _resolve_active_scene_id(self.show_sections, self.playhead_seconds),
        }
        return {**base, **authored_keys, **live}

    def update_show_section(self, section_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        """Update one editable show section in-place.

        Cycle-3 panel 3C-H2: routed through `_replace_show_sections_locked`
        for hash bookkeeping; persistence uses caller-locked helper.
        """
        updated_section: dict[str, Any] | None = None
        with self._lock, self._persistence_lock:
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
                # Build the new base list with this section replaced;
                # then route through the canonical helper.
                new_base = copy.deepcopy(self._base_show_sections)
                if index < len(new_base):
                    new_base[index] = copy.deepcopy(updated)
                else:
                    new_base.append(copy.deepcopy(updated))
                self._replace_show_sections_locked(new_base)
                payload = self._show_plan_payload_locked()
                self._persist_show_plan_locked(payload)
                updated_section = copy.deepcopy(self.show_sections[index])
                break
        return updated_section

    def _show_plan_payload_locked(self) -> dict[str, Any]:
        """Build the persisted show-plan payload.

        Cycle-3 panel NC-7 + cycle-4 panel Codex-HIGH-2 fix: persists
        `_base_show_sections` (authored truth, no intent overlay) plus
        `operator_intents` separately, plus the v2-added `timeline_flags`
        and `staged_look`. On load, `__post_init__` reconstructs the
        post-intent `show_sections` by calling
        `_refresh_operator_intents_locked`.
        """
        return {
            "track_key": self.track_key,
            "track_title": self.track_title,
            "track_artist": self.track_artist,
            "file_name": self.file_name,
            "duration_seconds": self.duration_seconds,
            "structure_markers": [dict(marker) for marker in self.structure_markers],
            # Cycle-3 panel NC-7: persist base (pre-intent) NOT post-intent.
            "show_sections": copy.deepcopy(self._base_show_sections),
            "selection_mode": _normalize_selection_mode(self.selection_mode),
            "selection_variance": _normalize_selection_variance(self.selection_variance),
            "venue_mode": _normalize_venue_mode(self.venue_mode),
            "metadata_confidence": copy.deepcopy(self.metadata_confidence),
            "operator_intents": copy.deepcopy(self.operator_intents),
            "metadata_source": _normalize_metadata_source(self.metadata_source),
            # v2 additions:
            "timeline_flags": copy.deepcopy(self.timeline_flags),
            "staged_look": copy.deepcopy(self.staged_look),
        }

    def _persist_show_plan_locked(self, payload: dict[str, Any]) -> None:
        """Caller-locked persistence helper.

        Cycle-2 panel NC-2 fix: caller MUST hold both `self._lock` and
        `self._persistence_lock`. Helper does NOT re-acquire (the cycle-2
        re-entry deadlock). Cycle-4 panel Codex-MEDIUM: preserves shipped
        post-save bookkeeping (updates `show_plan_path` / `show_source`
        from the callback result).
        """
        callback = self._save_callback
        if callback is None:
            return
        try:
            result = callback(payload)
        except Exception as exc:
            logger.warning("show_plan save failed", error=str(exc))
            raise
        if result:
            self.show_plan_path = str(result)
            self.show_source = "show_plan"

    def persist_current_show_plan(self) -> str | None:
        """Persist the current show plan if a callback is configured.

        Cycle-3 panel 3C-H2: holds joint-lock for the entire read-and-persist
        so disk state cannot diverge from memory state.
        """
        with self._lock, self._persistence_lock:
            payload = self._show_plan_payload_locked()
            self._persist_show_plan_locked(payload)
            return self.show_plan_path or None

    def request_seek(self, position_seconds: float) -> float:
        """Seek the backing transport and refresh exported playhead state.

        Cycle-5 panel Codex-HIGH-1 fix: a seek can cross an intent-expiry
        boundary. Refresh intents AND recompute hashes so downstream
        snapshot consumers see the post-expiry authored state.
        """
        callback = self._seek_callback
        if callback is None:
            raise RuntimeError("Playback transport is not seekable")
        new_position = callback(position_seconds)
        with self._lock:
            self.playhead_seconds = max(0.0, min(float(new_position), self.duration_seconds))
            self.finished = self.playhead_seconds >= self.duration_seconds
            self._refresh_operator_intents_locked()
            self._recompute_authored_hash_locked()
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

        with self._lock, self._persistence_lock:
            self.selection_mode = normalized_mode
            self.selection_variance = normalized_variance
            # Cycle-3 panel 3C-H2: route through canonical helper for hash
            # bookkeeping. Operator drafts do not survive a regeneration —
            # the authored state they were layered against no longer exists.
            self.staged_look = None
            self._replace_show_sections_locked(regenerated_sections)
            payload = self._show_plan_payload_locked()
            self._persist_show_plan_locked(payload)
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
        """Apply a typed operator steering intent to the current playback plan.

        Cycle-3 panel 3C-H2 + cycle-4 panel C4C-C1: joint-locked write
        path; routes through `_replace_show_sections_locked` so the hash
        bookkeeping fires correctly. Signature unchanged from shipped.
        """
        normalized_intent = _normalize_operator_intent(intent)
        if not normalized_intent:
            raise RuntimeError("Unsupported operator intent")
        normalized_scope = _normalize_operator_scope(scope)
        normalized_target = _normalize_operator_target(target)
        normalized_amount = round(_clamp(float(amount), 0.0, 1.0), 3)

        with self._lock, self._persistence_lock:
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
            # Re-route section update through the canonical helper so
            # `_authored_hash` / `_flags_hash` bookkeeping fires.
            # `_base_show_sections` stays the same; helper's internal
            # `_refresh_operator_intents_locked` reads the new
            # `operator_intents` and overlays them.
            self._replace_show_sections_locked(copy.deepcopy(self._base_show_sections))
            payload = self._show_plan_payload_locked()
            self._persist_show_plan_locked(payload)
        return self.snapshot()

    def bind_track_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """Resolve live track metadata into playback metadata and a show plan.

        Cycle-1 panel UF-16 + cycle-2 panel NC-2: joint-locked write path.
        Cycle-3 panel 3C-H2 + cycle-4 panel Codex-HIGH-2: installs persisted
        operator_intents AND timeline_flags hint AND staged_look BEFORE
        `_replace_show_sections_locked` runs, so the helper sees the
        complete authored state in one pass.
        """
        callback = self._metadata_bind_callback
        if callback is None:
            raise RuntimeError("Playback metadata binding is not configured")

        binding = callback(dict(metadata))
        if not isinstance(binding, dict):
            raise RuntimeError("Playback metadata binding did not return a payload")

        with self._lock, self._persistence_lock:
            self.track_title = str(binding.get("track_title") or self.track_title or self.file_name)
            self.track_artist = str(binding.get("track_artist") or self.track_artist)
            self.track_key = str(binding.get("track_key") or self.track_key)
            self.file_name = str(binding.get("file_name") or self.file_name or self.track_title)
            self.structure_markers = [
                dict(marker) for marker in binding.get("structure_markers", self.structure_markers)
            ]
            binding_show_sections = copy.deepcopy(binding.get("show_sections", self.show_sections))
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
            # Install persisted operator_intents BEFORE _replace_show_sections_locked
            # runs (cycle-4 panel Codex-HIGH-2). Helper's internal
            # _refresh_operator_intents_locked overlays them onto the new base.
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
            # Cycle-1 panel UF-16: stage mutation INSIDE the locked region.
            persisted_stage = binding.get("staged_look")
            self.staged_look = copy.deepcopy(persisted_stage) if isinstance(persisted_stage, dict) else None
            # Hint the helper with persisted flag ordering; helper rejects
            # if content doesn't match the freshly-derived flags.
            persisted_flags = binding.get("timeline_flags")
            if isinstance(persisted_flags, list):
                self._persisted_timeline_flags_hint = list(persisted_flags)
            self.server_time = time.time()
            self._replace_show_sections_locked(binding_show_sections)
            self.transport_revision += 1
            payload = self._show_plan_payload_locked()
            self._persist_show_plan_locked(payload)
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
