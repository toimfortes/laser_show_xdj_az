"""Shared runtime context for process-local control-plane services."""

from __future__ import annotations

import atexit
import concurrent.futures
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
from photonic_synesthesia.core.threadhygiene import (
    DaemonThreadPoolExecutor,
    shutdown_executor,
)
from photonic_synesthesia.platform.operator_workspace import build_operator_workspace_banks
from photonic_synesthesia.platform.staging_lane import (
    commit_staged_look as _commit_staged_look_helper,
)
from photonic_synesthesia.platform.staging_lane import (
    stage_look as _stage_look_helper,
)
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

# Cycle-3 destructive review F-EXEC + F-TIMEOUT: serialize show-plan
# regeneration on a single dedicated worker thread so two FastAPI
# requests can never run the AI scorer concurrently (eliminates
# module-level shared-state races inside `_default_show_sections` /
# `_ai_assisted_pattern_score`). Bounds the lock-hold time even if
# the regen wedges (5 second hard ceiling); the FastAPI handler
# returns RuntimeError instead of holding `_lock` indefinitely.
#
# Cycle-3-rev-2 R7 fix (Kilo + Gemini convergent): the prior
# replace-executor-on-timeout pattern leaked a CPU-busy thread per
# timeout. Repeated user retries → multiple zombie threads running
# the AI scorer concurrently → defeats F-EXEC's serialization guarantee
# AND eventually exhausts CPU (Gemini's "OS-level CPU starvation"
# CRITICAL — possibly the actual root cause of the catastrophic
# system hang the user experienced).
#
# Cycle-3-rev-2 R7 pattern: the executor is permanent (never replaced).
# A non-blocking `_REGEN_INFLIGHT` lock gates submissions: if another
# regen is in flight, new attempts return RuntimeError immediately
# (FastAPI handler converts to HTTP 409). Caller has to wait for the
# current regen to finish before triggering another. If the original
# regen wedges, all retries 409 — but no new threads spawn, so CPU
# stays bounded.
_REGEN_EXECUTOR = DaemonThreadPoolExecutor(
    max_workers=1, thread_name_prefix="playback-regen",
)
_REGEN_INFLIGHT = Lock()
_REGEN_TIMEOUT_SECONDS = 5.0


# Cycle-6 B4: the module-level executor never had a shutdown path. At
# interpreter exit, Python's `concurrent.futures.thread._python_exit`
# atexit handler fires `shutdown(wait=True)` — if a regen worker is
# wedged (e.g., stuck inside a deep director.palettes computation),
# that blocks interpreter exit indefinitely. Register our own atexit
# that beats Python's to the punch and uses the bounded-wait helper.
# ThreadPool has no children to kill, so the helper falls back to
# `shutdown(wait=True)` — but by the time Python's handler runs, ours
# has already set `_shutdown_thread=True` and cleared the queue, so
# the second shutdown is a cheap no-op.
def _shutdown_regen_executor_at_exit() -> None:
    shutdown_executor(_REGEN_EXECUTOR, timeout=2.0, name="playback-regen")


atexit.register(_shutdown_regen_executor_at_exit)


def _try_acquire_regen_slot() -> bool:
    """Non-blocking attempt to claim the regen slot. Returns False
    immediately if a regen is already in flight (cycle-3-rev-2 R7).
    """
    return _REGEN_INFLIGHT.acquire(blocking=False)


def _release_regen_slot() -> None:
    """Release the regen slot. Safe to call even if not held — the
    runtime context's `_regenerate_selection` releases unconditionally
    in a `finally` block.
    """
    try:
        _REGEN_INFLIGHT.release()
    except RuntimeError:
        # Already released (defensive — the finally pattern in
        # `_regenerate_selection` should make this impossible).
        pass


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


def _deep_overlay(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursive overlay: nested dicts merge by key; everything else replaces.

    Cycle-1 panel UF-12 fix: cycle-1 plan used `dict.update()` which is
    shallow — it overwrote authored nested dicts wholesale. This walks
    the two key paths the stage can touch (`cue_recipe`, `laser_program`)
    and overlays only the keys the operator supplied. Lists are treated
    as full replacement when the stage explicitly provides one (matches
    operator UI semantics where a list edit is always explicit).
    """
    out = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_overlay(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _deep_merge_section(
    authored: dict[str, Any],
    stage_cue_recipe: dict[str, Any],
    stage_laser_program: dict[str, Any],
) -> dict[str, Any]:
    """Merge an operator stage into an authored section without data loss."""
    merged = copy.deepcopy(authored)
    merged["cue_recipe"] = _deep_overlay(merged.get("cue_recipe") or {}, stage_cue_recipe)
    merged["laser_program"] = _deep_overlay(merged.get("laser_program") or {}, stage_laser_program)
    return merged


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

    # Persistence serializer lock. Cycle-3 review D2 fix initially split
    # the locks but introduced a last-writer-loses race (a 4-reviewer panel
    # caught it as cycle-3-rev-2 R1 — Codex CRITICAL, Gemini D1, Kilo).
    # Final pattern (cycle-3-rev-2 R1+R3 fix):
    #     with self._persistence_lock:        # acquired FIRST — serializes writers
    #         with self._lock:                # brief — memory mutation only
    #             self.<mutate state>
    #             payload = self._show_plan_payload_locked()
    #         # _lock released — graph tick free; persistence_lock still held
    #         self._persist_show_plan_locked(payload)
    #         with self._lock:                # brief reacquire for post-save bookkeeping
    #             self.<update show_plan_path/show_source from save callback>
    # Properties:
    #   - Disk writes ordered with memory commits (closes UF-15 — last-writer-loses)
    #   - `_lock` hold time bounded to in-memory operations (closes cycle-3 D2 — graph tick never blocks on disk)
    #   - post-save bookkeeping under `_lock` (closes cycle-3-rev-2 R3 — `show_plan_path` no longer mutated outside the lock the graph tick reads under)
    _persistence_lock: Lock = field(default_factory=Lock, repr=False)

    # Hint for persisted timeline_flags ordering across rebind (cycle-2
    # panel NC-1: declared as a slots field). Cleared after each use.
    _persisted_timeline_flags_hint: list[dict[str, Any]] | None = field(default=None, repr=False)
    _audio_available: bool = field(default=False, repr=False)
    _ilda_export_available: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        self.selection_mode = _normalize_selection_mode(self.selection_mode)
        self.selection_variance = _normalize_selection_variance(self.selection_variance)
        self.venue_mode = _normalize_venue_mode(self.venue_mode)
        self.metadata_source = _normalize_metadata_source(self.metadata_source)
        # Cache media availability once at construction. The graph tick
        # publishes snapshots at 50 Hz; repeated `Path.is_file()` probes in
        # `_snapshot_internal_locked()` turn a pure memory snapshot into disk
        # I/O on the hot path.
        self._audio_available = bool(self.file_path and Path(self.file_path).is_file())
        self._ilda_export_available = bool(
            self.ilda_export_path and Path(self.ilda_export_path).is_file()
        )
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

    def _refresh_operator_intents_locked(self) -> int:
        """Recompute show_sections from base + active intents, in place.

        Returns: count of intents removed by expiry (cycle-3 destructive
        review D3). Callers can skip the SHA1 hash recompute when the
        result is 0 — i.e. when no intent expired and so authored content
        cannot have changed via this path. Drops per-tick cost in
        `update_transport` from ~0.5 ms to negligible.

        Cycle-2 panel UF-4 fix: writes `self.show_sections[:]` instead of
        `self.show_sections = ...` so the list identity is preserved. The
        plan's "_replace_show_sections_locked is the only reassignment
        path" invariant relies on this.
        """
        prior_intent_count = len(self.operator_intents)
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
        return prior_intent_count - len(active_intents)

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
        """Public writer. Cycle-3-rev-2 R1+R3 lock pattern:
        `_persistence_lock` outermost (serializes writers + preserves
        disk-vs-memory commit order), `_lock` brief inside for memory
        ops only. Closes UF-15 (last-writer-loses) AND keeps the
        50 Hz graph tick unblocked during disk I/O.
        """
        with self._persistence_lock:
            with self._lock:
                self._replace_show_sections_locked(show_sections)
                payload = self._show_plan_payload_locked()
            saved_path = self._persist_show_plan_locked(payload)
            if saved_path:
                with self._lock:
                    self.show_plan_path = saved_path
                    self.show_source = "show_plan"
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
        moved past TTL). Post-refresh `_recompute_authored_hash_locked()`
        catches that case so the authored cache and `_timeline_flag_revision`
        stay in sync.

        Cycle-3 destructive review D3 fix: gate the hash recompute on actual
        intent-expiry (refresh returns the count). Cycle-4 measured 0.5 ms
        per call at 70 KB authored state; at 50 Hz that's 24 ms/sec
        unconditionally — meaningful CPU burn. Intents expire rarely;
        skipping the recompute when nothing expired drops the steady-state
        cost to near-zero.
        """
        with self._lock:
            self.playhead_seconds = max(0.0, min(playhead_seconds, self.duration_seconds))
            self.playing = playing
            self.finished = finished
            self.realtime = realtime
            self.speed = max(0.01, speed)
            expired_count = self._refresh_operator_intents_locked()
            if expired_count > 0:
                self._recompute_authored_hash_locked()
            self.server_time = time.time()
            self.transport_revision += 1

    def apply_live_binding(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if str(payload.get("state") or "") != "bound":
                return copy.deepcopy(self._snapshot_internal_locked())
            self.track_key = str(payload.get("resolved_track_key") or self.track_key)
            self.track_title = str(payload.get("track_title") or self.track_title)
            self.track_artist = str(payload.get("track_artist") or self.track_artist)
            self.metadata_source = _normalize_metadata_source(
                payload.get("metadata_source", self.metadata_source)
            )
            try:
                if payload.get("duration_seconds") is not None:
                    self.duration_seconds = max(0.0, float(payload.get("duration_seconds") or 0.0))
            except (TypeError, ValueError):
                pass
            try:
                if payload.get("playhead_seconds") is not None:
                    self.playhead_seconds = max(
                        0.0,
                        min(float(payload.get("playhead_seconds") or 0.0), self.duration_seconds),
                    )
            except (TypeError, ValueError):
                pass
            if payload.get("playing") is not None:
                self.playing = bool(payload["playing"])
            if payload.get("finished") is not None:
                self.finished = bool(payload["finished"])
            if payload.get("realtime") is not None:
                self.realtime = bool(payload["realtime"])
            if payload.get("speed") is not None:
                try:
                    self.speed = max(0.01, float(payload["speed"]))
                except (TypeError, ValueError):
                    pass
            self.metadata_bound_at = time.time()
            self.server_time = self.metadata_bound_at
            self.transport_revision += 1
            aliased = self._snapshot_internal_locked()
        return copy.deepcopy(aliased)

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
        export_available = self._ilda_export_available
        audio_available = self._audio_available
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
        payload: dict[str, Any] | None = None
        # Cycle-3-rev-2 R1+R3 lock pattern: persistence_lock outermost,
        # _lock brief inside for memory ops only.
        #
        # Cycle-5 HIGH (R3): the previous impl did SIX `copy.deepcopy()`
        # calls per single-field edit, including ONE full-list deepcopy
        # of `_base_show_sections`. For a 5-min show that's ~20 ms
        # inside `_lock` — enough to drop multiple 50 Hz graph frames
        # per UI patch. The cost is structural: we only need to deep-
        # copy the SECTION being modified (so mutations don't leak
        # back via aliased references), not the whole list.
        with self._persistence_lock:
            with self._lock:
                for index, section in enumerate(self.show_sections):
                    if str(section.get("id")) != section_id:
                        continue
                    # Deepcopy ONLY the target base section (its nested
                    # cue_recipe/laser_program dicts must not alias).
                    base_source = (
                        self._base_show_sections[index]
                        if index < len(self._base_show_sections)
                        else section
                    )
                    updated = copy.deepcopy(base_source)
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
                    # Build the new base via SHALLOW list copy + single-
                    # element replacement. Other section dicts remain
                    # aliased with the old `_base_show_sections` until
                    # `_replace_show_sections_locked` re-seats them via
                    # its own deepcopy. Total deepcopy work: one section
                    # here + the helper's one full-list deepcopy.
                    new_base = list(self._base_show_sections)
                    if index < len(new_base):
                        new_base[index] = updated
                    else:
                        new_base.append(updated)
                    self._replace_show_sections_locked(new_base)
                    payload = self._show_plan_payload_locked()
                    updated_section = copy.deepcopy(self.show_sections[index])
                    break
            if payload is not None:
                saved_path = self._persist_show_plan_locked(payload)
                if saved_path:
                    with self._lock:
                        self.show_plan_path = saved_path
                        self.show_source = "show_plan"
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

    def _persist_show_plan_locked(self, payload: dict[str, Any]) -> str | None:
        """Caller-locked persistence helper.

        Cycle-2 panel NC-2 + cycle-3-rev-2 R1+R3 fix:
        - Caller MUST hold `self._persistence_lock` (serializes writers
          + preserves disk-write order vs memory commits).
        - Caller MUST NOT hold `self._lock` (graph tick must be free
          to publish snapshots during disk I/O).
        - Helper RETURNS the save callback's result string; caller is
          responsible for assigning `self.show_plan_path` / `self.show_source`
          under `self._lock`. Cycle-3-rev-2 R3: those fields are read by
          `_snapshot_internal_locked` under `self._lock`, so writes to
          them must happen under the same lock to avoid memory-barrier
          violation across the FastAPI thread + 50 Hz graph tick.

        Returns: the path string from the save callback (or None).
        """
        callback = self._save_callback
        if callback is None:
            return None
        try:
            result = callback(payload)
        except Exception as exc:
            logger.warning("show_plan save failed", error=str(exc))
            raise
        return str(result) if result else None

    def persist_current_show_plan(self) -> str | None:
        """Persist the current show plan if a callback is configured.

        Cycle-3-rev-2 R1+R3 lock pattern: persistence_lock outermost,
        _lock brief inside.
        """
        with self._persistence_lock:
            with self._lock:
                payload = self._show_plan_payload_locked()
            saved_path = self._persist_show_plan_locked(payload)
            with self._lock:
                if saved_path:
                    self.show_plan_path = saved_path
                    self.show_source = "show_plan"
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
            # Cycle-3 destructive review D3: gate hash recompute on actual
            # expiry (a seek across an intent's TTL → expiry → hash bump).
            expired_count = self._refresh_operator_intents_locked()
            if expired_count > 0:
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
            # Cycle-5 HIGH (Review B/C — regen stomps concurrent edits):
            # snapshot the authored hash at submit time. If concurrent
            # writers (update_show_section, apply_operator_intent) mutate
            # authored state while the bg worker runs, the hash will have
            # changed by commit time and we refuse to clobber their edit
            # with our stale regeneration output. Without this check, a
            # ~5s regen window is a stomp-risk every time the operator
            # edits during AI scoring.
            submit_authored_hash = self._authored_hash
        normalized_mode = _normalize_selection_mode(selection_mode if selection_mode is not None else current_mode)
        normalized_variance = _normalize_selection_variance(
            selection_variance if selection_variance is not None else current_variance
        )
        if normalized_mode == current_mode and normalized_variance == current_variance:
            # Cycle-4 post-merge audit Review B HIGH-6: this no-op short-
            # circuit doubles as the idempotency guard for client-side
            # retries. Scenario:
            #   1. client PATCH selection-mode=ai_assisted, 10s timeout
            #   2. server regen completes, state flips to ai_assisted
            #   3. client's fetch aborts on timeout anyway
            #   4. user clicks again, second PATCH ai_assisted arrives
            # Step 4 lands here (current mode == requested mode) and
            # returns a snapshot without re-running the regen. A "double
            # regen" is only possible if the client retries with a
            # DIFFERENT value from what the server now holds, which is
            # the user's current intent by definition. No further
            # idempotency-key header needed.
            return self.snapshot()

        # Cycle-3 destructive review F-EXEC + F-TIMEOUT: run the
        # regen_callback (which calls into `_default_show_sections` →
        # AI scorer) on a dedicated single-thread executor with a hard
        # timeout. Closes:
        #   - F-EXEC: AI scorer's module-level caches (`_pattern_candidates`,
        #     `_stable_weighted_choice` state) are not guaranteed thread-safe;
        #     serializing on one thread eliminates the race.
        #   - F-TIMEOUT: if the scorer wedges (math NaN, semantic profile
        #     corruption, infinite softmax loop), the timeout bounds the
        #     lock-hold-via-blocked-handler scenario.
        # Cycle-3-rev-2 R7 fix: in-flight guard. Refuse new regens while
        # one is running so the AI scorer's non-thread-safe module state
        # never sees concurrent access AND zombie threads can't accumulate.
        if not _try_acquire_regen_slot():
            logger.warning(
                "playback_regenerate_in_flight",
                mode=normalized_mode,
                variance=normalized_variance,
            )
            raise RuntimeError(
                "Show-plan regeneration already in flight — wait for it "
                "to finish before triggering another."
            )
        # Post-merge cycle-4 audit HIGH-4 (Review B): assign
        # `slot_released_by_worker` BEFORE the inner try so any exception
        # (including a TimeoutError that happens before our `else` branch
        # could reach the assignment) leaves the flag in a defined state.
        # This removes the `except UnboundLocalError:` defensive catch
        # that used to guard against this; the flag is now always bound
        # when `finally` runs.
        slot_released_by_worker = False
        try:
            try:
                future = _REGEN_EXECUTOR.submit(
                    regenerate_callback, normalized_mode, normalized_variance,
                )
                regenerated_sections = future.result(timeout=_REGEN_TIMEOUT_SECONDS)
            except concurrent.futures.TimeoutError as exc:
                # Hung worker can't be cancelled. Leave it running and
                # the in-flight slot HELD until it eventually returns.
                # New regen attempts get 409 Conflict from the handler
                # (cycle-3-rev-2 R7: prevents zombie thread accumulation
                # that would otherwise cause OS-level CPU starvation).
                # NOTE: don't release the slot here — the worker still has
                # it. We deliberately leak the slot for the duration of
                # the wedged regen to bound CPU.
                logger.error(
                    "playback_regenerate_timeout",
                    mode=normalized_mode,
                    variance=normalized_variance,
                    timeout_seconds=_REGEN_TIMEOUT_SECONDS,
                )

                # Schedule slot release for when the worker eventually
                # finishes (may be never; that's OK — it just means
                # subsequent regens 409 forever, which is honest about
                # the broken state).
                def _release_when_done(fut):
                    _release_regen_slot()
                future.add_done_callback(_release_when_done)
                # Mark slot-release as the worker's responsibility.
                slot_released_by_worker = True
                raise RuntimeError(
                    f"Show-plan regeneration timed out after {_REGEN_TIMEOUT_SECONDS}s "
                    f"for mode={normalized_mode!r}, variance={normalized_variance:.3f}"
                ) from exc
            if not isinstance(regenerated_sections, list):
                raise RuntimeError("Playback regeneration did not return show sections")
        finally:
            # Post-merge cycle-4 audit HIGH-4 (Review B): `slot_released_by_worker`
            # is pre-assigned above so this `finally` is unconditional and
            # needs no UnboundLocalError guard. The timeout branch flips
            # the flag to True and hands off to `add_done_callback`; every
            # other path keeps it False and we release here. `_release_regen_slot`
            # itself is idempotent (catches RuntimeError from re-release).
            if not slot_released_by_worker:
                _release_regen_slot()

        # Cycle-3-rev-2 R1+R3 lock pattern.
        with self._persistence_lock:
            with self._lock:
                # Cycle-5 HIGH: stomp-protection. If authored state
                # changed while regen was running, refuse to overwrite
                # the operator's edit. The client should re-request
                # regen with fresh mode/variance values.
                if self._authored_hash != submit_authored_hash:
                    logger.warning(
                        "playback_regenerate_stomp_refused",
                        submit_hash=submit_authored_hash[:12] if submit_authored_hash else None,
                        current_hash=self._authored_hash[:12] if self._authored_hash else None,
                        mode=normalized_mode,
                        variance=normalized_variance,
                    )
                    raise RuntimeError(
                        "Show-plan regeneration refused: authored state changed "
                        "while the regen was running. Retry after the other edit completes."
                    )
                self.selection_mode = normalized_mode
                self.selection_variance = normalized_variance
                # Operator drafts do not survive a regeneration — the
                # authored state they were layered against no longer exists.
                self.staged_look = None
                self._replace_show_sections_locked(regenerated_sections)
                payload = self._show_plan_payload_locked()
            saved_path = self._persist_show_plan_locked(payload)
            if saved_path:
                with self._lock:
                    self.show_plan_path = saved_path
                    self.show_source = "show_plan"
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

        # Cycle-3-rev-2 R1+R3 lock pattern.
        with self._persistence_lock:
            with self._lock:
                # Cycle-5 HIGH (Review 2 + Review 3): cap operator_intents
                # to prevent DoS + unbounded deepcopy cost on every
                # graph tick. Intents with empty `expires_at` are
                # "permanent until cleared," so without a cap a flood
                # can exhaust memory AND starve the hot path. 50 is the
                # recommended cap from Review 3; evicts oldest by
                # `applied_at` if exceeded.
                _MAX_OPERATOR_INTENTS = 50
                if len(self.operator_intents) >= _MAX_OPERATOR_INTENTS:
                    # Drop oldest by applied_at. Preserve recent intents.
                    self.operator_intents.sort(key=lambda i: i.get("applied_at", 0.0))
                    evict_count = len(self.operator_intents) - _MAX_OPERATOR_INTENTS + 1
                    del self.operator_intents[:evict_count]
                    logger.warning(
                        "operator_intents_cap_reached_evicted_oldest",
                        cap=_MAX_OPERATOR_INTENTS,
                        evicted=evict_count,
                    )
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
                self._replace_show_sections_locked(copy.deepcopy(self._base_show_sections))
                payload = self._show_plan_payload_locked()
            saved_path = self._persist_show_plan_locked(payload)
            if saved_path:
                with self._lock:
                    self.show_plan_path = saved_path
                    self.show_source = "show_plan"
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

        # Cycle-3-rev-2 R1+R3 lock pattern.
        with self._persistence_lock:
            with self._lock:
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
                persisted_stage = binding.get("staged_look")
                self.staged_look = copy.deepcopy(persisted_stage) if isinstance(persisted_stage, dict) else None
                persisted_flags = binding.get("timeline_flags")
                if isinstance(persisted_flags, list):
                    self._persisted_timeline_flags_hint = list(persisted_flags)
                self.server_time = time.time()
                self._replace_show_sections_locked(binding_show_sections)
                self.transport_revision += 1
                payload = self._show_plan_payload_locked()
            saved_path = self._persist_show_plan_locked(payload)
            if saved_path:
                with self._lock:
                    self.show_plan_path = saved_path
                    self.show_source = "show_plan"
        return self.snapshot()

    # --- Task 4: operator preview/commit staging lane ---------------------

    def set_staged_look(
        self,
        *,
        section_id: str,
        cue_recipe: dict[str, Any],
        laser_program: dict[str, Any],
    ) -> dict[str, Any]:
        """Stage a look for operator preview.

        Cycle-1 panel UF-11 preview-only contract: the runtime graph reads
        `show_sections` ONLY; `staged_look` surfaces in `playback_snapshot`
        for UI preview and nowhere else. Bumps `_authored_hash` (cache
        invalidation) but NOT `_flags_hash` (trigger-router ledger
        preserved — cycle-2 panel NC-3 split). Cycle-1 panel UF-6:
        `_recompute_authored_hash_locked` is the explicit invalidation
        signal so the next `snapshot()` call rebuilds the authored cache.
        """
        if not isinstance(cue_recipe, dict) or not isinstance(laser_program, dict):
            raise RuntimeError("Invalid staged look payload")
        # Cycle-3-rev-2 R1+R3 lock pattern.
        with self._persistence_lock:
            with self._lock:
                if not any(str(section.get("id")) == section_id for section in self.show_sections):
                    raise RuntimeError("Unknown section id")
                self.staged_look = _stage_look_helper(
                    section_id=section_id,
                    cue_recipe=cue_recipe,
                    laser_program=laser_program,
                )
                self.server_time = time.time()
                self.transport_revision += 1
                self._recompute_authored_hash_locked()
                payload = self._show_plan_payload_locked()
                staged = copy.deepcopy(self.staged_look)
            saved_path = self._persist_show_plan_locked(payload)
            if saved_path:
                with self._lock:
                    self.show_plan_path = saved_path
                    self.show_source = "show_plan"
        return staged

    def commit_staged_look(self) -> dict[str, Any]:
        """Commit `staged_look` into the authored section.

        Cycle-1 panel SF-1 fix: recompute target section by id AND fail
        closed if the playhead has advanced past the staged section's
        end (operator must re-stage against current authored state).
        Cycle-1 panel UF-12 fix: use `_deep_merge_section` (not
        `dict.update`) so deeply-nested authored fields survive
        operator overrides for the keys they didn't touch. After commit,
        `staged_look` is cleared and the merged section becomes the new
        authored state.
        """
        # Cycle-3-rev-2 R1+R3 lock pattern.
        with self._persistence_lock:
            with self._lock:
                if not self.staged_look:
                    raise RuntimeError("No staged look")
                committed = _commit_staged_look_helper(self.staged_look)
                target_id = str(committed["section_id"])
                target_index: int | None = None
                for idx, section in enumerate(self._base_show_sections):
                    if str(section.get("id")) == target_id:
                        target_index = idx
                        break
                if target_index is None:
                    raise RuntimeError("Staged section no longer exists; please re-stage")
                target_section = self._base_show_sections[target_index]
                section_end = float(target_section.get("end_seconds", 0.0))
                if self.playhead_seconds > section_end:
                    raise RuntimeError(
                        "Playhead advanced past staged section; please re-stage against the current section"
                    )
                updated_sections = copy.deepcopy(self._base_show_sections)
                updated_sections[target_index] = _deep_merge_section(
                    authored=updated_sections[target_index],
                    stage_cue_recipe=copy.deepcopy(committed["cue_recipe"]),
                    stage_laser_program=copy.deepcopy(committed["laser_program"]),
                )
                self.staged_look = None
                self._replace_show_sections_locked(updated_sections)
                payload = self._show_plan_payload_locked()
            saved_path = self._persist_show_plan_locked(payload)
            if saved_path:
                with self._lock:
                    self.show_plan_path = saved_path
                    self.show_source = "show_plan"
        return committed


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
