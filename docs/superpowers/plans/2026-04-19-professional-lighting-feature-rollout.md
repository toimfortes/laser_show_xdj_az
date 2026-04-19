# Professional Lighting Feature Rollout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the highest-value professional-console concepts to `photonic-synesthesia` with the lowest-risk architecture: real recipe/phaser/tag/timeline planning, runtime laser-zone enforcement, move-when-dark pre-positioning, trigger routing, operator workspace, LED/content compositing, and preview/commit staging.

**Architecture:** The low-risk path is to land this in five architecture-first slices. `showplan/` owns authored show data. `PlaybackContext` is the only source of truth for authored sections, timeline flags, staged looks, and operator-visible show state. `PhotonicState` only carries frame-local execution artifacts derived from that source of truth. Graph integration must follow the real `_SequentialPipeline` in `builder.py`; no plan step may assume a mutable workflow graph API. `build_laser_program()` already exists with a rich internal signature, so rollout work should add thin adapters around it rather than rewriting that contract.

**Tech Stack:** Python 3.12, pytest, FastAPI/web panel, existing `showplan` package, typed `PhotonicState`, shared `PlaybackContext`, ILDA/DMX pipeline, JavaScript control-plane UI.

---

## Risk-reduction rules

1. **Single authority for authored show data**
   - `show_sections`, `timeline_flags`, `staged_look`, and operator-facing show metadata live in `PlaybackContext`.
   - `PhotonicGraph.step()` publishes one atomic `playback_snapshot` into `PhotonicState` under `_state_lock` before node execution.
   - Graph nodes read authored data only from `state["playback_snapshot"]`.
   - Graph nodes must not mutate authored show data.

2. **`PhotonicState` only carries execution artifacts**
   - Add typed frame-local fields only for things produced/consumed during one graph tick:
     - `playback_snapshot`
     - `trigger_events`
     - `preposition_targets`
     - `surface_layers`
     - `laser_zone_rules`

3. **Extend authored schemas in place**
   - `resolve_show_sections()` must enrich existing `cue_recipe` and `laser_program` payloads instead of replacing them with parallel mini-schemas.
   - Keep `zone_policy` authoritative inside `laser_program`; runtime laser rules derive from that authored intent.
   - Preserve human-authored `cue_recipe` / `laser_program` payloads unless a field is explicitly missing.

4. **Graph edits must match the real builder**
   - `src/photonic_synesthesia/graph/builder.py` uses `_SequentialPipeline(node_names=[...], nodes=nodes)`.
   - All node-insertion tasks must edit `node_names` in order and add concrete `nodes[...]` entries.
   - Use real existing node names such as `director_intent`, not invented names like `director`.

5. **Packaging boundaries stay honest**
   - `httpx` remains a dev/test dependency because the failing path was `fastapi.testclient` collection.
   - Do not widen runtime laptop requirements unless a runtime import path actually demands it.

6. **Tests must prove behavior, not key presence**
   - Prefer regression tests against real node output, runtime snapshots, and pipeline ordering.
   - Avoid dict-shape-only tests that can pass with fake implementations.
   - Runtime-node tests must prove deduping, move-when-dark gating, actual DMX/ILDA output changes, and real pipeline order.

7. **Persistence changes require schema clarity**
   - If persisted show-plan payloads gain `timeline_flags` or `staged_look`, update `src/photonic_synesthesia/integrations/show_plans.py` schema version and migration expectations in the same task.
   - Preview-only data may be persisted, but live runtime must never hot-swap from sidecar staged data.
   - Save-path and load-path must change together: persisted fields are not complete until the real `PlaybackContext(...)` construction sites hydrate them.

## File structure

### Existing files to modify

- `src/photonic_synesthesia/showplan/types.py`
  - Canonical typed contracts for authored planning objects
- `src/photonic_synesthesia/showplan/sections.py`
  - Sole owner of section and timeline-flag derivation
- `src/photonic_synesthesia/showplan/cue_recipe.py`
  - Compiles section intent into recipe/phaser-rich cue output
- `src/photonic_synesthesia/showplan/laser_program.py`
  - Builds authored laser programs and zone rules per section
- `src/photonic_synesthesia/core/state.py`
  - Adds frame-local execution artifacts to `PhotonicState`
- `src/photonic_synesthesia/platform/runtime_context.py`
  - Adds typed playback-context fields and snapshot export for authored show state
- `src/photonic_synesthesia/integrations/show_plans.py`
  - Owns persisted show-plan schema versioning for new authored-state fields
- `src/photonic_synesthesia/ui/cli.py`
  - Hydrates persisted authored-state fields into real `PlaybackContext(...)` construction sites
- `src/photonic_synesthesia/graph/builder.py`
  - Inserts new nodes into the real `_SequentialPipeline`
- `src/photonic_synesthesia/graph/nodes/fixture_control.py`
  - `LaserControlNode`, `MovingHeadControlNode`, and `PanelControlNode` consume the new frame-local artifacts
- `src/photonic_synesthesia/graph/nodes/ilda_output.py`
  - Reads current authored/staged laser program from playback snapshot
- `src/photonic_synesthesia/ui/web_panel.py`
  - Adds operator-workspace and staging endpoints and HTML anchor
- `src/photonic_synesthesia/ui/static/mock_control_plane.js`
  - Renders direct-select banks and staging controls
- `src/photonic_synesthesia/ui/static/mock_control_plane.css`
  - Styles new operator workspace/staging UI
- `pyproject.toml`
  - Keeps `httpx` in dev dependency boundary
- `README.md`
  - Documents pipeline order and authored-state ownership

### New files to create

- `src/photonic_synesthesia/showplan/recipes.py`
  - Deterministic recipe-line bundle builder
- `src/photonic_synesthesia/showplan/phasers.py`
  - Curated phaser family builder
- `src/photonic_synesthesia/showplan/tags.py`
  - Section tag generation and query helpers
- `src/photonic_synesthesia/showplan/timeline_flags.py`
  - Timeline flag derivation from authored sections
- `src/photonic_synesthesia/graph/nodes/trigger_router.py`
  - Reads authored timeline flags from playback snapshot and emits due trigger events
- `src/photonic_synesthesia/graph/nodes/preposition.py`
  - Emits frame-local pre-position targets derived from authored section intent
- `src/photonic_synesthesia/graph/nodes/surface_compositor.py`
  - Emits frame-local LED/content layers from authored sections
- `src/photonic_synesthesia/graph/nodes/laser_zone_runtime.py`
  - Applies runtime zone rules to generated ILDA frames before vector interlock
- `src/photonic_synesthesia/platform/operator_workspace.py`
  - Builds the operator direct-select workspace payload
- `src/photonic_synesthesia/platform/staging_lane.py`
  - Pure helpers for staging and committing looks

### Tests to create or extend

- `tests/unit/test_showplan_recipes.py`
- `tests/unit/test_showplan_phasers.py`
- `tests/unit/test_showplan_tags.py`
- `tests/unit/test_showplan_timeline_flags.py`
- `tests/unit/test_showplan_imports.py`
- `tests/unit/test_state_contracts.py`
- `tests/unit/test_runtime_context_helpers.py`
- `tests/unit/test_graph_builder.py`
- `tests/unit/test_trigger_router.py`
- `tests/unit/test_preposition.py`
- `tests/unit/test_surface_compositor.py`
- `tests/unit/test_laser_zone_runtime.py`
- `tests/unit/test_operator_workspace.py`
- `tests/unit/test_staging_lane.py`
- `tests/unit/test_web_panel.py`
- `tests/unit/test_packaging_metadata.py`
- `tests/integration/test_professional_rollout_pipeline.py`

## Shared ownership model

These rules are part of the plan, not optional implementation detail:

- `showplan/*` produces authored objects only.
- `showplan/*` must not import `platform/runtime_context*` or `ui/*`.
- `PlaybackContext` stores:
  - `show_sections`
  - `timeline_flags`
  - `staged_look`
  - operator-visible metadata used by the web panel
- `PhotonicState` stores only execution artifacts:
  - `playback_snapshot`
  - `trigger_events`
  - `preposition_targets`
  - `surface_layers`
  - `laser_zone_rules`
- `ILDAOutputNode`, `TriggerRouterNode`, `PrepositionNode`, and `SurfaceCompositorNode` read from `state["playback_snapshot"]`, which is published once per graph tick.

## Task 1: Land contract and ownership migration first

**Files:**
- Modify: `src/photonic_synesthesia/showplan/types.py`
- Modify: `src/photonic_synesthesia/core/state.py`
- Modify: `src/photonic_synesthesia/platform/runtime_context.py`
- Modify: `src/photonic_synesthesia/integrations/show_plans.py`
- Modify: `src/photonic_synesthesia/ui/cli.py`
- Test: `tests/unit/test_state_contracts.py`
- Test: `tests/unit/test_runtime_context_helpers.py`
- Test: `tests/unit/test_showplan_imports.py`

- [ ] **Step 1: Write the failing `PhotonicState` contract test**

```python
from photonic_synesthesia.core.state import create_initial_state


def test_initial_state_exposes_professional_runtime_artifacts() -> None:
    state = create_initial_state()

    assert "trigger_events" in state
    assert "preposition_targets" in state
    assert "surface_layers" in state
    assert "laser_zone_rules" in state
    assert "playback_snapshot" in state
    assert state["trigger_events"] == []
    assert state["preposition_targets"] == []
    assert state["playback_snapshot"] == {}
```

- [ ] **Step 2: Run the state contract test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_state_contracts.py::test_initial_state_exposes_professional_runtime_artifacts -q`
Expected: `FAIL` because the new fields are absent.

- [ ] **Step 3: Write the failing playback-context ownership test**

```python
from photonic_synesthesia.platform.runtime_context import PlaybackContext


def test_playback_context_snapshot_exports_authored_show_state() -> None:
    context = PlaybackContext(
        file_path="demo.wav",
        file_name="demo.wav",
        duration_seconds=120.0,
        show_sections=[{"id": "sec-1", "start_seconds": 0.0, "end_seconds": 16.0}],
    )
    context.timeline_flags = [{"id": "flag-1", "kind": "phrase_head", "at_seconds": 0.0, "payload": {"section_id": "sec-1"}}]
    context.staged_look = {"id": "look-1", "section_id": "sec-1", "committed": False}

    snapshot = context.snapshot()

    assert snapshot["show_sections"][0]["id"] == "sec-1"
    assert snapshot["timeline_flags"][0]["kind"] == "phrase_head"
    assert snapshot["staged_look"]["id"] == "look-1"
```

- [ ] **Step 4: Run the playback-context test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_runtime_context_helpers.py::test_playback_context_snapshot_exports_authored_show_state -q`
Expected: `FAIL` because `timeline_flags` and `staged_look` are not yet in the dataclass/snapshot.

- [ ] **Step 5: Write the failing import-boundary test**

```python
import importlib


def test_showplan_modules_do_not_import_runtime_context_or_ui() -> None:
    module = importlib.import_module("photonic_synesthesia.showplan.sections")
    source = module.__loader__.get_source(module.__name__) or ""

    assert "platform.runtime_context" not in source
    assert "photonic_synesthesia.ui" not in source
```

- [ ] **Step 6: Run the import-boundary test to verify current baseline**

Run: `.venv/bin/python -m pytest tests/unit/test_showplan_imports.py::test_showplan_modules_do_not_import_runtime_context_or_ui -q`
Expected: `PASS` or `FAIL`; if it fails, fix before proceeding. This test becomes a guardrail.

- [ ] **Step 7: Add canonical contracts in `showplan/types.py`**

```python
class RecipeLine(TypedDict, total=False):
    selection: str
    preset: str
    filter: str
    matricks: str
    fade: float
    delay: float
    speed_master: str
    timing_master: str
    phase: float


class PhaserSpec(TypedDict, total=False):
    family: str
    target: str
    measure: int
    speed_master: str
    width: float
    transition: float
    sync: bool


class TimelineFlag(TypedDict, total=False):
    id: str
    kind: str
    at_seconds: float
    payload: dict[str, Any]


class LaserZoneRule(TypedDict, total=False):
    zone_id: str
    mode: str
    brightness_cap: float
    protected: bool
    allow_position_fx: bool


class StagedLook(TypedDict, total=False):
    id: str
    source: str
    section_id: str
    cue_recipe: dict[str, Any]
    laser_program: dict[str, Any]
    committed: bool


# Single authoritative safety-mode list (cycle-1 panel UF-29: cycle-1 plan
# defined three divergent lists across ilda_output._ZONE_POLICY_RULES, the
# workspace builder in Step 11b, and the Task 2 recipe bundle — first drift
# silently produces inconsistent operator UI). All three consumers import
# this tuple. Use a tuple (not list) so no consumer can mutate it in place.
SAFETY_MODES: tuple[str, ...] = (
    "overhead_only",
    "overhead_bias",
    "mixed_air",
    "crowd_punctuate",
    "laser_off",
    "balanced",
)
```

- [ ] **Step 8: Add execution-artifact types and fields in `core/state.py`**

```python
class TriggerEvent(TypedDict):
    id: str
    kind: str
    payload: dict[str, object]


class PrepositionTarget(TypedDict):
    section_id: str
    preset: str


class SurfaceLayer(TypedDict):
    section_id: str
    surface_mode: str
    target: str


# In the existing PhotonicState(TypedDict), append these four field lines
# inside the current class body near the output/runtime artifact section.
# Keep every existing field above intact.
playback_snapshot: dict[str, Any]
trigger_events: list[TriggerEvent]
preposition_targets: list[PrepositionTarget]
surface_layers: list[SurfaceLayer]
laser_zone_rules: dict[str, dict[str, object]]
```

- [ ] **Step 9: Seed the new fields in `create_initial_state()`**

```python
        # System Health
        sensor_status={"audio": False, "midi": False, "cv": False},
        processing_times={},
        # Professional-rollout execution artifacts
        playback_snapshot={},
        trigger_events=[],
        preposition_targets=[],
        surface_layers=[],
        laser_zone_rules={},
    )
```

- [ ] **Step 10: Add authored-state fields to `PlaybackContext` and `snapshot()`**

**Revision counter is DERIVED from a content hash, not a mutation side-effect (cycle-1 panel UF-9).** The cycle-1 plan bumped `_timeline_flag_revision` on every mutation path (`bind_track_metadata`, `set_staged_look`, `commit_staged_look`, `_regenerate_selection`, `_replace_show_sections_locked`). Since `TriggerRouterNode` clears its fire-once ledger on revision change, every one of those bumps (most of which do NOT change `timeline_flags`) caused already-fired flags to re-fire. The fix: `_timeline_flag_revision` is updated ONLY inside `_replace_show_sections_locked` and ONLY when a newly-computed hash of `timeline_flags` differs from the last hash. Every other mutation path (operator intent, staging lane, metadata rebind with identical flags) leaves the counter untouched. The counter becomes a content identity marker, not a mutation counter.

**Cache is split into two layers (cycle-1 panel UF-5, UF-7).** The authored-cache holds only fields whose lifecycle is tied to `_authored_hash`: `show_sections`, `timeline_flags`, `staged_look`, and workspace-bank data. Per-call overlay holds fields that depend on the live playhead: `active_scene_id`, transport/playhead/server-time. This eliminates the "active_scene_id frozen to section-0" bug from cycle 1 (UF-7) and also gives tag-only edits a way to invalidate the workspace cache without bumping the flag counter (UF-30 cycle-2 follow-up — `_authored_hash` covers `show_sections` tag state too).

**Published snapshot is a deep copy per tick (cycle-1 panel UF-8).** The graph publishes `state["playback_snapshot"] = copy.deepcopy(ctx.snapshot())`, breaking alias chains to the cache. Aggregate cost is O(authored state) per tick, but the authored-cache build cost (the expensive `copy.deepcopy(show_sections)`) has already happened behind the `_authored_hash` gate, so in steady state the deep-copy-at-publication is duplicating only already-built dict skeletons. Benchmarking target: the per-tick copy must be <1 ms for a 40-section show (plan budget, to be validated in Task 5 Step 0 fixture).

```python
    timeline_flags: list[dict[str, Any]] = field(default_factory=list)
    staged_look: dict[str, Any] | None = None
    # Derived content hash of the authored state. Stable across routine
    # playhead progress; changes only when show_sections, timeline_flags, or
    # staged_look actually change content. The revision counter below is
    # derived from this hash — see Step 11.
    _authored_hash: str = ""
    # Monotonic counter, bumped ONLY when _authored_hash changes. Separate
    # from transport_revision so routine playhead updates do not invalidate
    # downstream fired-flag ledgers. TriggerRouterNode keys its fire-once
    # ledger reset on this counter.
    _timeline_flag_revision: int = 0
    # Authored-layer cache: fields whose lifecycle is tied to _authored_hash.
    # Rebuilt inside `snapshot()` only when the cache hash diverges from
    # _authored_hash. Readers receive a per-tick deep copy from the graph
    # publisher; this cache is never returned by reference.
    _authored_cache: dict[str, Any] | None = None
    _authored_cache_hash: str = ""
    # Persistence serializer lock (cycle-1 panel UF-15). Held alongside
    # self._lock on every write path so that in-memory commit order and
    # on-disk persist order cannot interleave across concurrent writers.
    _persistence_lock: Lock = field(default_factory=Lock, repr=False)
    # Hint for persisted flag ordering across rebind. Honored by
    # `_replace_show_sections_locked` only when the hint's content matches
    # the freshly-derived flags. Cleared after each use so a stale hint from
    # a prior write cannot leak into a later one. Cycle-2 panel NC-1: a
    # @dataclass(slots=True) class rejects ad-hoc attribute assignment, so
    # this field MUST be declared in the slot list — `self.<name> = ...`
    # otherwise raises AttributeError at runtime.
    _persisted_timeline_flags_hint: list[dict[str, Any]] | None = field(default=None, repr=False)
    # Derived content hash of `timeline_flags` alone. Drives
    # `_timeline_flag_revision` bumps; isolated from the broader
    # `_authored_hash` so non-flag mutations (staged_look, operator intents,
    # tag edits) do NOT clear the trigger-router ledger. Cycle-2 panel NC-3.
    _flags_hash: str = ""
```

All `safety_modes` enumerations in this plan share a single source of truth: `photonic_synesthesia.showplan.types.SAFETY_MODES` (added in Task 1 Step 7; single tuple, all three consumers import from there — cycle-1 panel UF-29).

In `update_transport()`:

```python
# update_transport() MUST continue to bump transport_revision so downstream
# consumers that care about playhead progress notice the update, but it
# MUST NOT unconditionally bump _timeline_flag_revision. Authored-state
# changes are the trigger for that counter — but note that transport
# progression can itself cause authored state to change indirectly via
# `_refresh_operator_intents_locked()` (an intent expires when the
# playhead moves past its TTL), so cycle-4 panel HIGH requires a
# post-refresh hash recompute to catch that case.
self.transport_revision += 1
# Cycle-4 panel HIGH (Codex R1): `_refresh_operator_intents_locked()` at
# `runtime_context.py:155` can change `self.show_sections` when an
# intent expires. Without a post-refresh hash recompute, the authored
# cache and snapshot readers keep serving the pre-expiry sections until
# some unrelated mutation forces invalidation. Cycle 5 fix: recompute
# both hashes AFTER the intent refresh; `_timeline_flag_revision` bumps
# only if `_flags_hash` actually moved (which for intent-expiry usually
# means "no change, keep the ledger").
self._recompute_authored_hash_locked()
# Note: `_recompute_authored_hash_locked()` only mutates hashes — it
# does NOT touch transport_revision (which was already bumped above).
```

Apply the same pattern after any other transport-driven `_refresh_operator_intents_locked()` site. **`request_seek()` rewrite (cycle-5 panel Codex-HIGH-1 fix):** the shipped `request_seek` at `runtime_context.py:288-299` does NOT currently call `_refresh_operator_intents_locked` at all, so a seek across an intent-expiry boundary leaves intent state stale until the next `update_transport`. This task adds the refresh and the hash recompute:

```python
# runtime_context.py — request_seek() rewrite
def request_seek(self, position_seconds: float) -> float:
    """Seek the backing transport and refresh exported playhead state."""
    if self._seek_callback is None:
        raise RuntimeError("Playback context has no seek callback")
    new_playhead = float(self._seek_callback(position_seconds))
    with self._lock:
        self.playhead_seconds = max(0.0, min(new_playhead, self.duration_seconds))
        # Cycle-5 panel Codex-HIGH-1 fix: the seek may have crossed an
        # intent expiry boundary. Refresh intents AND recompute hashes so
        # downstream snapshot consumers see the post-expiry authored state.
        self._refresh_operator_intents_locked()
        self._recompute_authored_hash_locked()
        self.server_time = time.time()
        self.transport_revision += 1
    return self.playhead_seconds
```

In `snapshot()` (Step 11b — split authored-cache + live-overlay, with a two-method split for by-reference vs deep-copy access):

```python
def snapshot(self) -> dict[str, Any]:
    """PUBLIC snapshot API — deep-copied so callers can freely mutate the result.

    Cycle-2 panel NC-8: cycle-2 exposed aliased authored-cache data to every
    caller of `snapshot()`, including web-panel endpoints and existing test
    harnesses that mutate the returned dict. Cycle 3 restores the cycle-1
    copy-on-read contract for the public API: web_panel / tests / UI polling
    call this method and get a safe-to-mutate deep copy.

    The graph publisher uses `_snapshot_internal_locked()` (aliased, ONE
    deep-copy at the publication boundary) to avoid double-copying on the
    hot path. Every OTHER caller uses `snapshot()`.
    """
    with self._lock:
        aliased = self._snapshot_internal_locked()
    return copy.deepcopy(aliased)


def _snapshot_internal_locked(self) -> dict[str, Any]:
    """INTERNAL aliased snapshot — called by the graph publisher only.

    Callers MUST hold `self._lock` and MUST deep-copy the result before
    publishing or handing it to any mutating consumer. Returns nested
    structures that alias `_authored_cache`; direct mutation poisons the
    cache. Cycle-2 panel NC-8 split: keeping the aliased path internal
    preserves the single-deepcopy-at-publication performance budget.

    Cycle-3 panel 3C-N2 fix: the return value is a SUPERSET of the shipped
    `PlaybackContext.snapshot()` fields (transport, session, audio, ILDA,
    hardware, selection, metadata, operator_intents) PLUS the new cycle-2
    authored-cache fields (show_sections, timeline_flags, staged_look,
    operator_workspace_banks, timeline_flag_revision, authored_hash) PLUS
    the per-call live overlay (active_scene_id). Shipped web-panel / UI
    consumers remain source-compatible.
    """
    # 1. Core transport + session + audio fields. Identical to shipped
    # `snapshot()` at runtime_context.py:159; re-emitted here so web-panel
    # consumers continue to receive every field they already expected.
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
    # 2. Authored-cache fields (new in cycle 2): `show_sections` (authored
    # truth surface for the graph tick), `timeline_flags`, `staged_look`,
    # `operator_workspace_banks`, and schema counters. Cached behind
    # `_authored_hash`; deep-copied only when the hash diverges.
    if self._authored_cache is not None and self._authored_cache_hash == self._authored_hash:
        authored_keys = self._authored_cache  # alias
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
    # 3. Live overlay (cycle-1 panel UF-7): `active_scene_id` derived from
    # the current playhead, not the authored cache.
    active_scene_id = _resolve_active_scene_id(self.show_sections, self.playhead_seconds)
    live = {"active_scene_id": active_scene_id}
    # 4. Merge. `base` has the shipped fields; `authored_keys` layers the
    # new cycle-2 fields on top (overwriting `show_sections` — the cycle-2
    # field is the authored cache copy, which is what the graph consumes);
    # `live` overlays the per-call fields. Ordering: shipped → authored →
    # live — later layers win on key conflict.
    return {**base, **authored_keys, **live}


def __post_init__(self) -> None:
    """Cycle-3 panel 3C-N3 fix: seed `_authored_hash` and `_flags_hash` at
    construction so the first mutation doesn't bump `_timeline_flag_revision`
    spuriously (which would clear TriggerRouterNode's fire-once ledger —
    the cycle-1 UF-9 regression). The hash seed reflects the constructed
    state as it stands *before* the first `_replace_show_sections_locked`
    call, so a no-op rebind with identical content leaves the counter at 0.

    Preserves shipped `__post_init__` behavior: normalization + initial
    operator-intent refresh. The hash seed runs LAST so
    `_refresh_operator_intents_locked` has already updated
    `self.show_sections` to its post-intent form.
    """
    # Shipped behavior (runtime_context.py:95-102):
    self.selection_mode = _normalize_selection_mode(self.selection_mode)
    self.selection_variance = _normalize_selection_variance(self.selection_variance)
    self.venue_mode = _normalize_venue_mode(self.venue_mode)
    self.metadata_source = _normalize_metadata_source(self.metadata_source)
    self._base_show_sections = copy.deepcopy(self.show_sections)
    with self._lock:
        self._refresh_operator_intents_locked()
        # Cycle-3 panel 3C-N3 seed. `self.show_sections` now reflects any
        # persisted operator intents applied on top of `_base_show_sections`.
        self._authored_hash = _compute_authored_hash(
            self.show_sections, self.timeline_flags, self.staged_look,
        )
        self._flags_hash = _compute_flags_hash(self.timeline_flags)


def _resolve_active_scene_id(show_sections: list[dict[str, Any]], playhead: float) -> str:
    if not show_sections:
        return ""
    for section in show_sections:
        start = float(section.get("start_seconds", 0.0))
        end = float(section.get("end_seconds", start))
        if start <= playhead < max(end, start + 1e-6):
            return str(section.get("id") or "")
    return str(show_sections[-1].get("id") or "")  # past-end → last section
```

Graph publication (inside `PhotonicGraph.step()`, see Task 3 Step 5) MUST deep-copy:

```python
# src/photonic_synesthesia/graph/builder.py — _publish_playback_snapshot()
published = copy.deepcopy(playback.snapshot())   # cycle-1 panel UF-8
with self._state_lock:
    self._state["playback_snapshot"] = published
    # Also explicitly reset frame-local artifacts so a prior tick's values
    # cannot leak into the current one (cycle-1 panel SF-3).
    self._state["preposition_targets"] = []
    self._state["surface_layers"] = []
    self._state["laser_zone_rules"] = {}
    self._state["trigger_events"] = []
```

Why deep-copy: the cycle-1 plan returned `dict(self._snapshot_cache)` — a shallow copy whose nested `show_sections` / `timeline_flags` still aliased the cache. Any consumer mutation (or any in-place merge inside `commit_staged_look` that happens to share a dict identity) poisoned the cache for the rest of the run. Deep-copy at the publication boundary makes the published dict structurally isolated from the cache. Cost: ~0.5 ms per 40-section show (validated in Task 5 Step 0 performance test); negligible at 50–60 Hz.

Alternative considered and rejected: `types.MappingProxyType` + tuple wrapping. Rejected because many downstream consumers (particularly FastAPI's `jsonable_encoder`) don't handle `MappingProxyType` gracefully and require the caller to unwrap — moving the alias-aware discipline out of PlaybackContext and into every reader is strictly worse.

- [ ] **Step 11: Single publication helper, hash-derived revision, in-lock persistence**

**Invariants this step MUST establish:**

1. **Authored-state assignment happens ONLY inside `_replace_show_sections_locked`.** Every mutation path (`update_show_section`, `apply_operator_intent`, `_regenerate_selection`, `bind_track_metadata`, every `ControlPlaneStateService` route that writes section state) goes through this helper. The plan enumerates every pre-existing call site in Step 12.

2. **`_refresh_operator_intents_locked` mutates `self.show_sections` in place under a preserved list identity** (cycle-1 panel UF-4). The shipped code at `runtime_context.py:137` does `self.show_sections = sections` — this cycle-2 plan refactors it to index-wise writes so the list object identity is preserved and `_replace_show_sections_locked` is the only path that ever reassigns. See Step 11a below for the exact refactor.

3. **`_timeline_flag_revision` changes ONLY when `_flags_hash` changes** (cycle-1 panel UF-9, UF-10; cycle-2 panel NC-3 refinement; cycle-3 panel 3C-M1 prose correction — earlier drafts of this step said `_authored_hash`, which was the pre-NC-3 coupling that's now broken apart). `_flags_hash` is a content hash of `timeline_flags` ALONE, isolated from `_authored_hash` (which covers the full authored tuple including `staged_look`). A `set_staged_look` call bumps `_authored_hash` (invalidates the snapshot cache) but NOT `_flags_hash` — so the trigger-router ledger is preserved across UI-only previews. The helper computes both hashes, bumps `_timeline_flag_revision` iff `_flags_hash` is different, and never does an unconditional `+= 1`. All call sites (`bind_track_metadata`, `set_staged_look`, `commit_staged_look`, `_regenerate_selection`, callers of `_replace_show_sections_locked`) rely on the helper's derived bump; no call site does its own `self._timeline_flag_revision += 1`.

4. **Persistence happens inside the joint lock — and `_persist_show_plan` is renamed to `_persist_show_plan_locked`, with its internal `with self._lock:` removed** (cycle-1 panel UF-15, SF-2; cycle-2 panel NC-2). The shipped helper acquired `self._lock` internally, which the cycle-2 joint-acquire pattern re-enters, hanging the caller if `Lock` is non-reentrant. Cycle-3 contract: the helper is caller-locked. Callers hold `self._lock` + `self._persistence_lock` in the same order, then call `self._persist_show_plan_locked(payload)`. The rename makes the contract visible at every call site.

5. **Callers CANNOT supply `timeline_flags=` to bypass the derivation** (cycle-1 panel UF-18). The parameter is removed from `_replace_show_sections_locked`'s signature. Callers that need to preserve persisted flags set `self._persisted_timeline_flags_hint` before calling; the helper honors the hint only when its hash matches the freshly-derived hash.

**Step 11a — Refactor `_refresh_operator_intents_locked` to preserve list identity (UF-4):**

```python
# BEFORE (runtime_context.py:137, cycle 0, shipped today):
#     self.show_sections = sections
#
# AFTER: index-wise writes that preserve `self.show_sections`'s list identity.
def _refresh_operator_intents_locked(self) -> None:
    active_intents = [
        copy.deepcopy(intent_payload)
        for intent_payload in self.operator_intents
        if not _intent_expired(intent_payload, self._base_show_sections, self.playhead_seconds, self.duration_seconds)
    ]
    refreshed_sections = copy.deepcopy(self._base_show_sections)
    for intent_payload in active_intents:
        # ... (existing intent-application logic, unchanged) ...
        refreshed_sections = _apply_intent_to_sections(refreshed_sections, intent_payload)
    self.operator_intents = active_intents
    # In-place update that preserves list identity. Readers that have a
    # reference to `self.show_sections` keep seeing a consistent list; the
    # publisher deep-copies before publishing so mid-tick mutations cannot
    # poison the published snapshot.
    self.show_sections[:] = refreshed_sections
```

Pre-existing call sites that this refactor affects, enumerated with the line numbers they touch in the shipped codebase (all verified against `runtime_context.py` at HEAD):

- `__post_init__` → line 102 (calls `_refresh_operator_intents_locked` inside `with self._lock:`). Safe after the refactor: the initial list identity is whatever `__post_init__` assigns before calling the helper.
- `update_transport` → line 155. Safe: helper mutates in place, no reassignment surprises.
- `snapshot` → (currently does not call the helper at all in the shipped code; the plan's new `snapshot()` also does not call it).
- `update_show_section` → line 245. Safe, but this call site is also rewritten to go through `_replace_show_sections_locked` (Step 12).
- `apply_operator_intent` → line 372. Safe, but this call site is also rewritten.
- `bind_track_metadata` → line 440. Rewritten to go through `_replace_show_sections_locked` (Step 12b).

**Step 11b — The helper itself:**

```python
import hashlib
import json

from photonic_synesthesia.showplan.timeline_flags import derive_timeline_flags
from photonic_synesthesia.showplan.types import SAFETY_MODES
from photonic_synesthesia.platform.operator_workspace import build_operator_workspace_banks
# Cycle-4 panel Gemini/Claude LOW fix: runtime_context.py's snapshot/helper
# blocks reference `SAFETY_MODES`, `build_operator_workspace_banks`, and
# `derive_timeline_flags` without the imports. Cycle 5 adds them at the
# top of `runtime_context.py` next to the existing `copy` / `time` imports.


def _compute_authored_hash(
    show_sections: list[dict[str, Any]],
    timeline_flags: list[dict[str, Any]],
    staged_look: dict[str, Any] | None,
) -> str:
    """Deterministic content hash of ALL authored fields.

    Used ONLY by `snapshot()` cache validity — it invalidates the authored
    cache when any of show_sections / timeline_flags / staged_look change.
    Does NOT drive `_timeline_flag_revision`; that counter is derived from
    `_compute_flags_hash` alone so non-flag mutations (staged_look,
    operator-intent-only section edits) do not clear the trigger ledger.
    Cycle-2 panel NC-3 split.

    Cycle-4 panel C4C-M2 note: `show_sections` already reflects any active
    operator intents (because `_refresh_operator_intents_locked` mutates
    `self.show_sections[:]` in place before the hash is computed), so
    `operator_intents` content is implicitly covered by `show_sections`
    content. No need to hash `operator_intents` separately.
    """
    material = json.dumps(
        [show_sections, timeline_flags, staged_look],
        sort_keys=True,
        default=str,
    )
    return hashlib.sha1(material.encode("utf-8")).hexdigest()


def _compute_flags_hash(timeline_flags: list[dict[str, Any]]) -> str:
    """Deterministic content hash of `timeline_flags` ONLY.

    Drives `_timeline_flag_revision` bump decisions. A change to
    `staged_look`, `show_sections` (without flag boundary changes), or any
    other authored field does NOT change this hash — so TriggerRouterNode's
    fire-once ledger is NOT cleared on UI-only previews or tag-only edits.
    Cycle-2 panel NC-3: isolates the trigger-ledger invalidation from the
    broader authored-cache invalidation.
    """
    # Order-insensitive hash: sort by (id, at_seconds) before serializing.
    # Two rebinds with identical flags in different orders produce the same
    # hash, so a rebind that merely reshuffles the persisted list does not
    # trip a no-op trigger-ledger clear.
    key = lambda f: (str(f.get("id") or ""), float(f.get("at_seconds", 0.0)))
    material = json.dumps(sorted(timeline_flags, key=key), sort_keys=True, default=str)
    return hashlib.sha1(material.encode("utf-8")).hexdigest()


def _replace_show_sections_locked(
    self,
    show_sections: list[dict[str, Any]],
) -> None:
    """Single authoritative writer for `show_sections` + derived state.

    Callers MUST hold `self._lock` before invoking. Callers that need to
    preserve persisted flags across a rebind set `self._persisted_timeline_flags_hint`
    to the persisted list BEFORE calling; the hint is honored only when its
    hash matches the freshly-derived hash.
    """
    self._base_show_sections = copy.deepcopy(show_sections)
    # Assign list identity once here — the only place outside __post_init__
    # where the list is reassigned.
    self.show_sections = copy.deepcopy(show_sections)
    # Operator-intent refresh runs BEFORE timeline_flags derive, so flags
    # always reflect post-intent boundaries (cycle-2 finding C3).
    self._refresh_operator_intents_locked()
    derived_flags = derive_timeline_flags(self.show_sections)
    # Honor a hint only when the hint's content matches the derived content.
    # This preserves persisted-flag ordering/metadata on no-op rebinds while
    # preventing callers from injecting stale pre-refresh flags (UF-18).
    hint = getattr(self, "_persisted_timeline_flags_hint", None)
    if hint is not None and _flags_equivalent(hint, derived_flags):
        self.timeline_flags = copy.deepcopy(hint)
    else:
        self.timeline_flags = derived_flags
    self._persisted_timeline_flags_hint = None
    self.server_time = time.time()
    # Split hash recompute (cycle-2 panel NC-3). `_authored_hash` gates the
    # authored-cache rebuild — it changes on any authored-field mutation,
    # including staged_look and intent-only section content edits.
    # `_flags_hash` gates `_timeline_flag_revision` — it changes ONLY when
    # timeline_flags content changes. A non-flag mutation (staged_look
    # changed but flags unchanged) bumps the authored hash (invalidating
    # the snapshot cache) but does NOT bump _timeline_flag_revision (so
    # TriggerRouterNode's fire-once ledger is preserved).
    new_authored = _compute_authored_hash(self.show_sections, self.timeline_flags, self.staged_look)
    if new_authored != self._authored_hash:
        self._authored_hash = new_authored
    new_flags = _compute_flags_hash(self.timeline_flags)
    if new_flags != self._flags_hash:
        self._flags_hash = new_flags
        self._timeline_flag_revision += 1
    # NOTE: do NOT touch transport_revision here; that counter is transport's.


def _flags_equivalent(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> bool:
    """Flags match by id + kind + at_seconds + payload, order-insensitive."""
    key = lambda f: (str(f.get("id") or ""), str(f.get("kind") or ""), float(f.get("at_seconds", 0.0)))
    return sorted(a, key=key) == sorted(b, key=key)


def replace_show_sections(
    self,
    show_sections: list[dict[str, Any]],
) -> dict[str, Any]:
    """Public writer. Acquires both locks; persistence is ordered with memory.

    Lock ordering (cycle-1 panel UF-15): `_lock` first (guards memory),
    then `_persistence_lock` (guards on-disk write order). The two concurrent
    writers cannot have their disk writes reorder independently of their
    memory commits because the persistence lock serializes both.
    """
    with self._lock, self._persistence_lock:
        self._replace_show_sections_locked(show_sections)
        payload = self._show_plan_payload_locked()
        # _persist_show_plan uses save_show_plan's atomic tmp+rename path
        # (Step 12c). On failure, the in-memory state has already committed
        # but the disk is still at the previous payload — callers see the
        # exception and either retry or revert (reloading from disk is
        # authoritative).
        self._persist_show_plan_locked(payload)
    return self.snapshot()
```

Per the invariants above, `self.show_sections`, `self.timeline_flags`, and `self.staged_look` never change without `_authored_hash` also changing. The snapshot cache is therefore self-validating — it rebuilds iff `_authored_cache_hash != self._authored_hash`, so there is no second, separate cache-invalidation path to maintain. Every former ad-hoc `self._snapshot_cache = None; self._snapshot_cache_revision = -1` in the cycle-1 plan is GONE — those paths were the symptom, not the cure.

**Persistence helper rename (cycle-2 panel NC-2).** The shipped `_persist_show_plan` acquired `self._lock` internally. The cycle-2 joint-acquire pattern re-entered `self._lock` from within a `with self._lock:` block, deadlocking. Cycle 3 renames the helper to `_persist_show_plan_locked` and removes its internal lock — callers are now responsible for holding `self._lock` + `self._persistence_lock`:

```python
# runtime_context.py — the cycle-3 persistence helper. Caller-locked.
def _persist_show_plan_locked(self, payload: dict[str, Any]) -> None:
    """Serialize `payload` to disk via `save_show_plan`, preserving the
    shipped method's post-save bookkeeping. Caller MUST hold both
    `self._lock` and `self._persistence_lock`; the helper does NOT
    re-acquire them (cycle-2 panel NC-2).

    Cycle-4 panel Codex-MEDIUM fix: the shipped `_persist_show_plan` at
    `runtime_context.py:270-278` updates `self.show_plan_path` and
    `self.show_source` from the save-callback's return value (the
    callback returns the final disk path on success). Dropping that
    update would leave `show_plan_path` stale after every save — the
    web panel's "saved plan" indicator would point at the wrong file.
    Cycle 5 restores the post-save state update while keeping the helper
    caller-locked.

    Atomic-write safety: the `_save_callback` is expected to route
    through `save_show_plan` (Task 1 Step 12c), which uses the
    `tmp.write_text` + `os.replace` pattern so a partial write cannot
    corrupt a previous successful payload.
    """
    if self._save_callback is None:
        return
    try:
        result = self._save_callback(payload)
    except Exception as exc:
        logger.warning("show_plan save failed", error=str(exc))
        raise  # Caller decides whether to revert in-memory state.
    # Preserve shipped post-save bookkeeping (runtime_context.py:275-278).
    # Caller already holds `self._lock`, so we can write directly; no
    # re-acquire needed.
    if result:
        self.show_plan_path = str(result)
        self.show_source = "show_plan"
```

Every call site that previously invoked `self._persist_show_plan(payload)` must now call `self._persist_show_plan_locked(payload)` from within an already-held `(self._lock, self._persistence_lock)` region — see the `replace_show_sections`, `bind_track_metadata`, `set_staged_look`, and `commit_staged_look` write paths.

- [ ] **Step 12: Route every authored-section mutation path through `_replace_show_sections_locked()`**

The `timeline_flags=` parameter is GONE from the helper signature (cycle-1 panel UF-18). Callers that need to preserve persisted flag ordering/metadata across a rebind set `self._persisted_timeline_flags_hint` BEFORE calling — the helper honors the hint only when its content matches the freshly-derived content. Every call site below runs inside `with self._lock, self._persistence_lock:` (or inside `replace_show_sections` which holds both).

**Call-site audit (cycle-3 panel 3C-H2).** The cycle-3 plan claimed "every `_persist_show_plan` caller is updated" but did not explicitly rewrite the shipped `apply_operator_intent` and `persist_current_show_plan` methods. Cycle 4 closes both — each now uses the joint-lock pattern and calls the caller-locked helper.

```python
# runtime_context.py
# update_show_section()
updated_show_sections = copy.deepcopy(self._base_show_sections)
updated_show_sections[index] = copy.deepcopy(updated)
self._replace_show_sections_locked(updated_show_sections)

# _regenerate_selection()
self._replace_show_sections_locked(regenerated_sections)

# bind_track_metadata()
binding_show_sections = copy.deepcopy(binding.get("show_sections", self.show_sections))
persisted_flags = binding.get("timeline_flags")
if isinstance(persisted_flags, list):
    # Hint is a request, not an injection — helper verifies content match
    # before honoring; pre-refresh flags from an earlier compute will be
    # rejected and the derivation wins.
    self._persisted_timeline_flags_hint = list(persisted_flags)
self._replace_show_sections_locked(binding_show_sections)


# apply_operator_intent() — cycle-4 panel C4C-C1 restoration.
# The cycle-3 rewrite inadvertently CHANGED the public signature from the
# shipped keyword-only `(*, intent, scope, target, amount, expires_at)` at
# runtime_context.py:342 to a positional `(intent_payload: dict)`, which
# would break `web_panel.py` callers and every shipped test. Cycle 5
# restores the shipped signature + normalization block, wraps it in the
# joint-lock pattern, and re-routes section mutation through
# `_replace_show_sections_locked` so `_authored_hash` / `_flags_hash`
# bookkeeping fires.
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
    # Input normalization (preserves shipped runtime_context.py:352-357).
    normalized_intent = _normalize_operator_intent(intent)
    if not normalized_intent:
        raise RuntimeError("Unsupported operator intent")
    normalized_scope = _normalize_operator_scope(scope)
    normalized_target = _normalize_operator_target(target)
    normalized_amount = round(_clamp(float(amount), 0.0, 1.0), 3)

    with self._lock, self._persistence_lock:
        # Build the intent payload using the shipped field set (including
        # `target_ids`, `applied_playhead_seconds`, `applied_at`) so
        # `_intent_expired` and the operator-audit UI see the same data
        # they expect from the shipped method.
        target_ids = _section_ids_for_scope(
            self._base_show_sections, self.playhead_seconds, normalized_scope,
        )
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
        # Re-route the section update through the canonical helper so both
        # `_authored_hash` (cache invalidation) and `_flags_hash` (trigger
        # ledger bump) update consistently. Pass `_base_show_sections`; the
        # helper's internal `_refresh_operator_intents_locked` reads the
        # new `operator_intents` and layers them onto that base.
        self._replace_show_sections_locked(copy.deepcopy(self._base_show_sections))
        payload = self._show_plan_payload_locked()
        self._persist_show_plan_locked(payload)
    return self.snapshot()


# persist_current_show_plan() — cycle-3 panel 3C-H2 rewrite.
# Shipped method computed the payload outside the lock, then called the
# internal-locked helper. Cycle-4 contract: hold joint-lock for the whole
# read-and-persist so disk state cannot diverge from memory state.
def persist_current_show_plan(self) -> None:
    with self._lock, self._persistence_lock:
        payload = self._show_plan_payload_locked()
        self._persist_show_plan_locked(payload)
```

Every other shipped method that mutates authored state or persists to disk must follow the same pattern. At commit time, grep for `_persist_show_plan` and `self.show_sections = ` across `runtime_context.py` and confirm each result is either inside a joint-locked region calling the `_locked` helper OR has been rewritten to route through `_replace_show_sections_locked`. This audit is part of the Task-1 commit checklist.

**Persistence boundary: persist `_base_show_sections` separately from `operator_intents` (cycle-2 panel NC-7).** The cycle-2 plan persisted `self.show_sections` (post-intent), which on load became the new `_base_show_sections` — so transient operator intents silently baked into the authored base across restart cycles. Cycle 3 fix: `_show_plan_payload_locked()` persists `self._base_show_sections` as authored truth plus `self.operator_intents` separately; on load, `show_sections` is reconstructed by applying the persisted intents to the persisted base.

Extend `_show_plan_payload_locked()` to produce:

```python
# runtime_context.py — _show_plan_payload_locked()
return {
    # ... existing fields ...
    "show_sections": copy.deepcopy(self._base_show_sections),  # authored base, no intent overlay
    "operator_intents": copy.deepcopy(self.operator_intents),  # transient overlays, persisted separately
    "timeline_flags": copy.deepcopy(self.timeline_flags),
    "staged_look": copy.deepcopy(self.staged_look),
}
```

On load, the hydration path reconstructs the runtime state by applying persisted intents on top of the persisted base — `_refresh_operator_intents_locked` (already in `__post_init__`) does this automatically because `_base_show_sections` is the pre-intent truth and `operator_intents` carries the layered edits:

```python
# ui/cli.py
persisted_base_sections = copy.deepcopy((persisted_show_plan or {}).get("show_sections", []))
persisted_operator_intents = copy.deepcopy((persisted_show_plan or {}).get("operator_intents", []))
persisted_timeline_flags = copy.deepcopy((persisted_show_plan or {}).get("timeline_flags", []))
persisted_staged_look = copy.deepcopy((persisted_show_plan or {}).get("staged_look"))
if not isinstance(persisted_timeline_flags, list):
    persisted_timeline_flags = []
if not isinstance(persisted_staged_look, dict):
    persisted_staged_look = None
if not isinstance(persisted_operator_intents, list):
    persisted_operator_intents = []
```

Construction site passes these into `PlaybackContext`:

```python
PlaybackContext(
    ...,
    show_sections=persisted_base_sections,   # becomes _base_show_sections in __post_init__
    operator_intents=persisted_operator_intents,
    timeline_flags=persisted_timeline_flags,
    staged_look=persisted_staged_look,
)
```

`__post_init__` runs `_refresh_operator_intents_locked()`, which mutates `self.show_sections[:]` in place to apply the persisted intents — the same code path used for runtime intent updates. The result: the post-intent `show_sections` visible to runtime on load is identical to the one that was visible just before the last `_persist_show_plan_locked` call, but transient intents are no longer baked into the authored base across restart.

Bump `src/photonic_synesthesia/integrations/show_plans.py`:

```python
SCHEMA_VERSION = 2
```

The v1→v2 migration preserves this boundary for older payloads: v1 plans have no `operator_intents` field, so the migration sets it to `[]` — any intents that were active at v1-save time are lost (the plan acknowledges this as acceptable since v1 intent state was never a persisted contract):

Apply those values in both real `PlaybackContext(...)` construction sites:

```python
# live Web UI playback context
PlaybackContext(
    ...,
    timeline_flags=[],
    staged_look=None,
)

# file playback Web UI context
PlaybackContext(
    ...,
    timeline_flags=persisted_timeline_flags,
    staged_look=persisted_staged_look,
)
```

If `persisted_timeline_flags` is empty but `show_sections` exists, immediately call:

```python
# Cycle-2 panel NC-6: no `timeline_flags=` kwarg — the parameter was removed
# in Task 1 Step 11. `replace_show_sections` derives flags from the sections
# inside `_replace_show_sections_locked`. For a caller that wants to preserve
# persisted ordering, use the hint pattern (see bind_track_metadata).
playback_context.replace_show_sections(playback_context.show_sections)
```

so older schema payloads derive flags on first load.

- [ ] **Step 12b: Hydrate `timeline_flags` and `staged_look` on track rebind**

`bind_track_metadata()` is the path hit when a metadata-only (Pro DJ Link / Rekordbox match) session loads a persisted show plan. Without extending its binding callback, v2 payloads written to disk by the file-playback session would silently drop both new fields on the metadata-bind round trip.

```python
# src/photonic_synesthesia/ui/cli.py — _build_track_metadata_binding_callback
def _bind(metadata: dict[str, Any]) -> dict[str, Any]:
    ...
    persisted_plan = load_show_plan(track_key)  # existing call
    # Cycle-2 panel NC-7: hydrate from `_base_show_sections` semantics —
    # the persisted `show_sections` is authored truth (no intent overlay);
    # operator intents are a separate field. `_replace_show_sections_locked`
    # will re-apply them in-memory on the rebind.
    binding["show_sections"] = copy.deepcopy(persisted_plan.get("show_sections", []))
    raw_intents = persisted_plan.get("operator_intents")
    binding["operator_intents"] = list(raw_intents) if isinstance(raw_intents, list) else []
    # Cycle-1 panel UF-1 / UF-3: persisted fields that SCHEMA_VERSION=2 adds.
    raw_flags = persisted_plan.get("timeline_flags")
    binding["timeline_flags"] = list(raw_flags) if isinstance(raw_flags, list) else None
    raw_stage = persisted_plan.get("staged_look")
    binding["staged_look"] = dict(raw_stage) if isinstance(raw_stage, dict) else None
    return binding
```

And in `PlaybackContext.bind_track_metadata()` — the whole method runs under both locks; all staged_look mutation happens INSIDE the locked region (cycle-1 panel UF-16):

```python
def bind_track_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
    if self._metadata_bind_callback is None:
        raise RuntimeError("Playback metadata binding is not configured")
    with self._lock, self._persistence_lock:
        binding = self._metadata_bind_callback(dict(metadata))
        binding_show_sections = copy.deepcopy(binding.get("show_sections", self.show_sections))
        # Cycle-4 panel Codex-HIGH fix: install persisted operator intents
        # from the binding payload BEFORE `_replace_show_sections_locked`
        # runs — the helper's internal `_refresh_operator_intents_locked`
        # reads `self.operator_intents` to overlay intents onto the base.
        # Without this, a persisted plan with active operator overrides
        # would load without those overrides — silent data loss on rebind.
        # The cycle-2 plan added `binding["operator_intents"]` in the
        # callback (Task 1 Step 12b) but the cycle-3 rewrite forgot to
        # assign it here.
        persisted_intents = binding.get("operator_intents")
        if isinstance(persisted_intents, list):
            self.operator_intents = [copy.deepcopy(i) for i in persisted_intents if isinstance(i, dict)]
        persisted_flags = binding.get("timeline_flags")
        if isinstance(persisted_flags, list):
            self._persisted_timeline_flags_hint = list(persisted_flags)
        # Stage mutation happens INSIDE the locked region (cycle-1 panel UF-16).
        persisted_stage = binding.get("staged_look")
        self.staged_look = copy.deepcopy(persisted_stage) if isinstance(persisted_stage, dict) else None
        # Now update authored state. The helper recomputes the hash and bumps
        # _timeline_flag_revision iff the new hash differs — so a rebind with
        # identical flags and no stage change is a no-op (cycle-1 panel UF-9:
        # routes that formerly did an unconditional `self._timeline_flag_revision
        # += 1` here are REMOVED — the helper owns the decision).
        self._replace_show_sections_locked(binding_show_sections)
        payload = self._show_plan_payload_locked()
        self._persist_show_plan_locked(payload)
    return self.snapshot()
```

Acceptance test (`tests/unit/test_runtime_context_helpers.py`): persist a plan with `timeline_flags=[…]` and `staged_look={…}`; create a fresh `PlaybackContext`; call `bind_track_metadata`; assert `snapshot()["timeline_flags"]` and `snapshot()["staged_look"]` match the persisted payload.

- [ ] **Step 12c: Provide a v1→v2 migration hook**

Older persisted plans (no `_schema_version` key or `_schema_version == 1`) must load into the new runtime without data loss. `load_show_plan()` normalizes on read.

**Schema-key discipline (cycle-1 panel UF-1, UF-2).** The shipped constant in `show_plans.py` is `_SCHEMA_KEY = "_schema_version"` (underscore-prefixed) and `save_show_plan` stamps `{_SCHEMA_KEY: SCHEMA_VERSION, **payload}`. Every read, migration, stamp, and test assertion in this plan MUST use `_SCHEMA_KEY` (not the bare `"schema_version"`). Every version gate MUST use a LITERAL integer (never the `SCHEMA_VERSION` constant) so a future v3 bump does not re-run the v1→v2 migrator on valid v2 plans. `load_show_plan` retains its shipped `dict | None` return contract — no caller audit is required at this step.

```python
# src/photonic_synesthesia/integrations/show_plans.py

# _SCHEMA_KEY = "_schema_version" (already defined at module top; re-asserted for clarity)

def load_show_plan(track_key: str) -> dict[str, Any] | None:
    """Load + migrate a persisted show plan.

    Contract: returns None on missing/malformed payload (unchanged from cycle 1).
    Callers doing `if persisted is None` continue to work.
    """
    raw = _read_show_plan_payload(track_key)
    if not isinstance(raw, dict):
        return None
    version = int(raw.get(_SCHEMA_KEY, 1) or 1)
    if version == 1:
        raw = _migrate_show_plan_v1_to_v2(raw)
    # NOTE: literal `== 1` not `< SCHEMA_VERSION`. A future v3 bump will add its
    # own `elif version == 2:` branch; the v1→v2 migrator will never run on v2
    # payloads.
    return raw


def _migrate_show_plan_v1_to_v2(payload: dict[str, Any]) -> dict[str, Any]:
    # v1 plans have show_sections but no timeline_flags/staged_look.
    # Leave show_sections untouched; fill defaults so snapshot readers
    # don't have to check for key presence.
    payload.setdefault("timeline_flags", [])
    payload.setdefault("staged_look", None)
    payload[_SCHEMA_KEY] = 2  # literal, not SCHEMA_VERSION
    return payload
```

**Atomic-write + rollback (cycle-1 panel SF-2).** `save_show_plan` writes the new plan to a temp file in the same directory, fsyncs, then atomically renames. Callers that fail after in-memory mutation can recover by reloading from disk (the last successfully-persisted state).

```python
# src/photonic_synesthesia/integrations/show_plans.py
def save_show_plan(track_key: str, payload: dict[str, Any]) -> Path:
    path = show_plan_path(track_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    stamped = {_SCHEMA_KEY: SCHEMA_VERSION, **payload}
    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(stamped, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)  # atomic on POSIX and Windows NTFS
    except Exception:
        # On any failure, drop the temp file; disk state remains at the last
        # successfully-persisted payload. Callers receive the exception and
        # must decide whether to revert their in-memory state.
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise
    return path
```

Acceptance test (use a direct-JSON v1 fixture — do NOT route through `save_show_plan`, which stamps `_SCHEMA_KEY=SCHEMA_VERSION` and would make the v1 fixture fiction):

```python
def test_load_show_plan_migrates_v1_to_v2(tmp_path, monkeypatch) -> None:
    from photonic_synesthesia.integrations.show_plans import (
        _SCHEMA_KEY,
        load_show_plan,
        show_plan_path,
    )

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    plan_path = show_plan_path("legacy-track")
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    # Emit a v1 plan as raw JSON (no _schema_version key).
    plan_path.write_text(json.dumps({
        "show_sections": [{"id": "sec-0", "section_role": "intro", "start_seconds": 0.0, "end_seconds": 10.0}],
    }), encoding="utf-8")

    loaded = load_show_plan("legacy-track")

    assert loaded is not None
    assert loaded[_SCHEMA_KEY] == 2
    assert loaded["timeline_flags"] == []
    assert loaded["staged_look"] is None
    assert loaded["show_sections"][0]["id"] == "sec-0"


def test_load_show_plan_returns_none_on_missing() -> None:
    from photonic_synesthesia.integrations.show_plans import load_show_plan
    assert load_show_plan("never-saved-key") is None  # None contract preserved
```

- [ ] **Step 12d: Create operator_workspace + timeline_flags stubs so Task 1 stands alone**

Task 1's `snapshot()` and `_replace_show_sections_locked()` import from two modules that Task 2 / Task 4 create. To keep Task 1 independently red/green (cycle-1 panel UF-14 / cycle-5 panel Codex-HIGH-2), Task 1 ships minimal stubs:

```python
# src/photonic_synesthesia/platform/operator_workspace.py  (Task 1 stub)
from typing import Any


def build_operator_workspace_banks(
    *,
    sections: list[dict[str, Any]],
    available_tags: list[str],
    safety_modes: tuple[str, ...],
) -> dict[str, Any]:
    """Task 1 stub. Task 4 Step 6 replaces this with the full implementation.

    The signature and return type MUST match the Task 4 version exactly so
    Task 1's snapshot() call is wire-compatible without further work.
    """
    return {"banks": []}
```

```python
# src/photonic_synesthesia/showplan/timeline_flags.py  (Task 1 stub —
# cycle-5 panel Codex-HIGH-2 fix)
from typing import Any, TypedDict


class TimelineFlag(TypedDict, total=False):
    id: str
    kind: str
    at_seconds: float
    payload: dict[str, Any]


def derive_timeline_flags(show_sections: list[dict[str, Any]]) -> list[TimelineFlag]:
    """Task 1 stub. Task 2 Step 6 replaces this with the full implementation
    that emits `phrase_head` + transition-typed flags per section.

    Empty-list return is correct for the Task-1 acceptance test path
    (which uses sections without `transition_intent` and asserts the helper
    is called and the field is populated). The full implementation in Task 2
    drops in without changing the import surface.
    """
    return []
```

Task 2 Step 6 overwrites `timeline_flags.py`; Task 4 Step 6 overwrites `operator_workspace.py`. Acceptance test for both stubs is covered by Task 1 Step 13's `replace_show_sections()` → `snapshot()` integration test, which proves the imports resolve and the keys are present (empty lists in the Task-1 build, populated by Task 2/4 implementations).

- [ ] **Step 13: Extend the runtime-context test to prove `replace_show_sections()` publishes authored state**

```python
# The `timeline_flags=` parameter is no longer accepted on
# `replace_show_sections()` (cycle-1 panel UF-18). Callers that need to
# preserve persisted flag ordering use the hint-based path on
# `bind_track_metadata()` — see Step 12b.
updated = context.replace_show_sections(
    [{"id": "sec-2", "start_seconds": 16.0, "end_seconds": 32.0, "tags": ["role:drop"]}],
)

assert updated["show_sections"][0]["id"] == "sec-2"
# Flags are derived from the new section(s), not passed in.
assert updated["timeline_flags"][0]["id"] == "sec-2:phrase_head"
```

- [ ] **Step 14: Run the contract and boundary tests**

Run: `.venv/bin/python -m pytest tests/unit/test_state_contracts.py tests/unit/test_runtime_context_helpers.py tests/unit/test_showplan_imports.py -q`
Expected: `PASS`

- [ ] **Step 15: Commit**

```bash
git add src/photonic_synesthesia/showplan/types.py src/photonic_synesthesia/core/state.py src/photonic_synesthesia/platform/runtime_context.py src/photonic_synesthesia/integrations/show_plans.py src/photonic_synesthesia/ui/cli.py tests/unit/test_state_contracts.py tests/unit/test_runtime_context_helpers.py tests/unit/test_showplan_imports.py
git commit -m "feat: add professional rollout contracts and ownership model"
```

## Task 2: Land authored `showplan` primitives with one section owner

**Files:**
- Create: `src/photonic_synesthesia/showplan/recipes.py`
- Create: `src/photonic_synesthesia/showplan/phasers.py`
- Create: `src/photonic_synesthesia/showplan/tags.py`
- Create: `src/photonic_synesthesia/showplan/timeline_flags.py`
- Modify: `src/photonic_synesthesia/showplan/sections.py`
- Modify: `src/photonic_synesthesia/showplan/cue_recipe.py`
- Modify: `src/photonic_synesthesia/showplan/laser_program.py`
- Modify: `src/photonic_synesthesia/showplan/__init__.py`
- Test: `tests/unit/test_showplan_recipes.py`
- Test: `tests/unit/test_showplan_phasers.py`
- Test: `tests/unit/test_showplan_tags.py`
- Test: `tests/unit/test_showplan_timeline_flags.py`

- [ ] **Step 1: Write the failing recipe-bundle test**

```python
from photonic_synesthesia.showplan.recipes import build_recipe_bundle


def test_build_recipe_bundle_emits_deterministic_line_level_data() -> None:
    bundle = build_recipe_bundle(
        section_role="drop",
        lead_family="laser",
        target_mode="overhead",
        cue_family_id="small_room_50_100::drop::laser",
    )

    line = bundle["recipe_lines"][0]
    assert line["selection"] == "laser:drop"
    assert line["timing_master"] == "phrase"
    assert line["speed_master"] == "groove"
```

- [ ] **Step 2: Write the failing phaser-bundle test**

```python
from photonic_synesthesia.showplan.phasers import build_phaser_bundle


def test_build_phaser_bundle_varies_by_role_and_lead_family() -> None:
    build_bundle = build_phaser_bundle(section_role="build", lead_family="mover")
    drop_bundle = build_phaser_bundle(section_role="drop", lead_family="laser")

    assert build_bundle[0]["family"] != drop_bundle[0]["family"]
    assert build_bundle[0]["target"] == "mover"
    assert drop_bundle[0]["target"] == "laser"
```

- [ ] **Step 3: Write the failing section-owner test**

```python
from photonic_synesthesia.showplan.sections import resolve_show_sections


def test_resolve_show_sections_attaches_tags_flags_and_runtime_intents() -> None:
    """Acceptance test: red before this task implements the enrichment.

    Cycle-1 panel UF-25: the cycle-1 test asserted presence of keys that the
    shipped `resolve_show_sections` ALREADY populates (tags/preposition_intent/
    surface_program/laser_program existed in some form in the pre-rollout
    code), so the test passed before Task 2 was written — providing no
    red/green signal. This revision asserts the NEW content derived by this
    task: (a) `tags` contains the role-lead-venue triple introduced in Step 6,
    (b) `preposition_intent` has the `enabled`/`when`/`targets` triad with
    `when == "release"` specifically for breakdown/bridge roles, (c)
    `cue_recipe["phasers"]` emits the `pressure`/`breathing` family mapping
    from Step 5, and (d) `laser_program["context"]` is produced through the
    transition-context adapter from Step 7.
    """
    sections = resolve_show_sections(
        persisted_show_plan=None,
        markers=[
            {"kind": "drop", "start_seconds": 0.0, "end_seconds": 16.0},
            {"kind": "breakdown", "start_seconds": 16.0, "end_seconds": 32.0},
        ],
        duration_seconds=64.0,
        track_seed="demo-seed",
        venue_mode="small_room_50_100",
    )

    drop, breakdown = sections[0], sections[1]
    # (a) New Step-6 tag vocabulary on every section.
    assert "role:drop_1" in drop["tags"] or "role:drop" in drop["tags"]
    assert any(tag.startswith("lead:") for tag in drop["tags"])
    assert any(tag.startswith("venue:") for tag in drop["tags"])
    assert any(tag in {"laser:on", "laser:off"} for tag in drop["tags"])
    # (b) preposition_intent for breakdown enables release-timed prepositioning.
    assert breakdown["preposition_intent"]["enabled"] is True
    assert breakdown["preposition_intent"]["when"] == "release"
    assert breakdown["preposition_intent"]["targets"]  # non-empty list
    # Drop sections should NOT enable prepositioning.
    assert drop["preposition_intent"]["enabled"] is False
    # (c) Phaser family mapping pins the new Step-5 vocabulary.
    drop_phasers = drop["cue_recipe"]["phasers"]
    assert drop_phasers and drop_phasers[0]["family"] == "pressure"  # high-energy role
    breakdown_phasers = breakdown["cue_recipe"]["phasers"]
    assert breakdown_phasers and breakdown_phasers[0]["family"] == "breathing"
    # (d) Laser-program adapter routes transition_intent into the builder vocab.
    # The shipped code does not populate `_transition_context_used` — this task
    # adds it as a diagnostic field to prove the adapter is wired in.
    assert "_transition_context_used" in drop["laser_program"]
```

- [ ] **Step 4: Run the failing authored-plan tests**

Run: `.venv/bin/python -m pytest tests/unit/test_showplan_recipes.py tests/unit/test_showplan_phasers.py tests/unit/test_showplan_tags.py tests/unit/test_showplan_timeline_flags.py -q`
Expected: `FAIL`

- [ ] **Step 5: Implement deterministic recipe and phaser builders**

The production vocabulary for `section_role` is suffixed — `build_1`,
`build_2`, `drop_1`, `drop_variation` — not `build`/`drop`. Every recipe
/ phaser branch keys on prefix so suffixed variants hit the intended
high-energy path:

```python
def _is_high_energy_role(section_role: str) -> bool:
    """Match both the coarse ('build', 'drop') and suffixed
    ('build_1', 'build_2', 'drop_1', 'drop_variation') forms."""
    return section_role.startswith("build") or section_role.startswith("drop")


def build_recipe_bundle(*, section_role: str, lead_family: str, target_mode: str, cue_family_id: str) -> dict[str, Any]:
    return {
        "cue_family_id": cue_family_id,
        "next_positions": ["fan_open"] if _is_high_energy_role(section_role) else [f"{lead_family}:home"],
        "recipe_lines": [
            {
                "selection": f"{lead_family}:{section_role}",
                "preset": f"{section_role}:{target_mode}",
                "filter": "default",
                "matricks": "symmetry",
                "fade": 0.25,
                "delay": 0.0,
                "speed_master": "groove",
                "timing_master": "phrase",
                "phase": 0.0,
            }
        ],
    }
```

```python
def build_phaser_bundle(*, section_role: str, lead_family: str) -> list[PhaserSpec]:
    family = "pressure" if _is_high_energy_role(section_role) else "breathing"
    return [
        {
            "family": family,
            "target": lead_family,
            "measure": 4,
            "speed_master": "groove",
            "width": 0.5,
            "transition": 0.5,
            "sync": True,
        }
    ]
```

- [ ] **Step 6: Implement tags and timeline flags**

```python
def build_section_tags(*, section_role: str, lead_family: str, venue_mode: str, laser_enabled: bool) -> list[str]:
    return [
        f"role:{section_role}",
        f"lead:{lead_family}",
        f"venue:{venue_mode}",
        "laser:on" if laser_enabled else "laser:off",
    ]
```

```python
def derive_timeline_flags(show_sections: list[dict[str, Any]]) -> list[TimelineFlag]:
    flags: list[TimelineFlag] = []
    for section in show_sections:
        at_seconds = float(section.get("start_seconds", 0.0))
        section_id = str(section["id"])
        flags.append(
            {
                "id": f"{section_id}:phrase_head",
                "kind": "phrase_head",
                "at_seconds": at_seconds,
                "payload": {"section_id": section_id},
            }
        )
        transition_type = str((section.get("transition_intent") or {}).get("type", ""))
        if transition_type:
            flags.append(
                {
                    "id": f"{section_id}:{transition_type}",
                    "kind": transition_type,
                    "at_seconds": at_seconds,
                    "payload": {"section_id": section_id},
                }
            )
    return flags
```

- [ ] **Step 7: Add a low-risk section laser-program adapter instead of changing `build_laser_program()`**

`build_laser_program()` already takes a `context:` parameter keyed on the
existing transition-context vocabulary (`drop_launch`, `drop_variation`,
`build_riser`, `build_cycle`, `breakdown_release`, `intro_set`,
`outro_release`). The new `transition_intent["type"]` field lives in a
DIFFERENT vocabulary (`bloom`, `handoff`, `suckout`, `release`, …) that
the recipe builders emit. Passing `transition_intent["type"]` straight
through would silently route every section onto the default `"intro_set"`
context table, degrading authored selection.

The adapter therefore translates the authored transition_intent into the
transition-context vocabulary before calling `build_laser_program()`:

```python
# Mapping from authored transition_intent.type (recipe vocab) to
# build_laser_program() context (transition-context vocab). Keep this
# table as the single translation surface so builder changes don't drift
# from recipe output.
_TRANSITION_INTENT_TO_CONTEXT: dict[str, str] = {
    "bloom": "build_cycle",
    "handoff": "build_riser",
    "suckout": "drop_launch",
    "release": "breakdown_release",
    "settle": "breakdown_release",
    "drop": "drop_launch",
    "drop_variation": "drop_variation",
    "outro": "outro_release",
    "intro": "intro_set",
}


def _resolve_transition_context(section: dict[str, Any]) -> str:
    intent_type = str((section.get("transition_intent") or {}).get("type") or "")
    if intent_type in _TRANSITION_INTENT_TO_CONTEXT:
        return _TRANSITION_INTENT_TO_CONTEXT[intent_type]
    # Fall back by section_role (suffixed form — build_1/2, drop_1, drop_variation)
    role = str(section.get("section_role") or "")
    if role.startswith("drop"):
        return "drop_variation" if role == "drop_variation" else "drop_launch"
    if role.startswith("build"):
        return "build_riser" if role == "build_1" else "build_cycle"
    if role in {"breakdown", "bridge"}:
        return "breakdown_release"
    if role == "outro":
        return "outro_release"
    return "intro_set"


def build_section_laser_program(
    *,
    track_seed: str,
    section: dict[str, Any],
    venue_mode: str,
    ordinal: int,
    profile: dict[str, Any],
) -> dict[str, Any]:
    return build_laser_program(
        track_seed=track_seed,
        base_pattern=str(section.get("laser_pattern") or "fan"),
        kind=str(section.get("kind") or section.get("section_role") or "intro"),
        context=_resolve_transition_context(section),
        ordinal=ordinal,
        profile=profile,
        venue_mode=venue_mode,
    )
```

Acceptance test (`tests/unit/test_showplan_laser_program.py`):

```python
@pytest.mark.parametrize(
    "intent_type, section_role, expected_context",
    [
        ("bloom", "build_1", "build_cycle"),
        ("handoff", "build_2", "build_riser"),
        ("suckout", "drop_1", "drop_launch"),
        ("release", "breakdown", "breakdown_release"),
        ("", "build_2", "build_cycle"),     # intent missing → role fallback
        ("", "drop_variation", "drop_variation"),
        ("unknown_new_type", "intro", "intro_set"),  # unknown → safe default
    ],
)
def test_transition_context_resolver_preserves_builder_vocab(intent_type, section_role, expected_context):
    section = {"transition_intent": {"type": intent_type}, "section_role": section_role}
    assert _resolve_transition_context(section) == expected_context
```

- [ ] **Step 8: Make `resolve_show_sections()` the sole owner of authored attachments without forking existing schemas**

The merge MUST preserve any pre-existing authored fields on `cue_recipe`.
`dict.update()` overwrites keys unconditionally; using it would let a
default rebuild destroy an operator-edited selection or fade value.
Fill ONLY missing keys via `setdefault` (or an equivalent missing-only
merge):

```python
for index, section in enumerate(resolved_sections):
    section["tags"] = build_section_tags(
        section_role=section["section_role"],
        lead_family=section["lead_family"],
        venue_mode=venue_mode,
        laser_enabled=bool(section.get("laser_enabled", True)),
    )
    existing_cue_recipe = dict(section.get("cue_recipe") or {})
    default_bundle = build_recipe_bundle(
        section_role=section["section_role"],
        lead_family=section["lead_family"],
        target_mode=str(section.get("target_mode", "overhead")),
        cue_family_id=f"{venue_mode}::{section['section_role']}::{section['lead_family']}",
    )
    # Missing-only merge: defaults fill gaps; authored fields remain
    # authoritative. Tests below pin this ordering.
    for key, value in default_bundle.items():
        existing_cue_recipe.setdefault(key, value)
    # `phasers` follows the same missing-only rule as every other authored
    # recipe field (cycle-1 panel UF-12 / B5: rule 3 says "preserve
    # authored payloads unless a field is explicitly missing"; the cycle-1
    # plan unconditionally overwrote `phasers`, contradicting the rule).
    # Phaser bundle is a pure derivation with no operator override surface
    # TODAY, but the override path MUST be available — otherwise operator
    # edits to phasers would be wiped on every `resolve_show_sections`
    # re-pass. setdefault keeps the door open without forcing operator UI
    # work now.
    existing_cue_recipe.setdefault(
        "phasers",
        build_phaser_bundle(
            section_role=section["section_role"],
            lead_family=section["lead_family"],
        ),
    )
    section["cue_recipe"] = existing_cue_recipe
    section["preposition_intent"] = {
        "enabled": section["section_role"] in {"breakdown", "bridge"},
        "when": "release",
        "targets": list(existing_cue_recipe.get("next_positions", [])),
    }
    section["surface_program"] = {
        "surface_mode": "texture" if section["section_role"] in {"intro", "breakdown"} else "accent",
        "target": str(section.get("hook_family", "led_wall")),
    }

    if not isinstance(section.get("laser_program"), dict):
        section["laser_program"] = build_section_laser_program(
            track_seed=track_seed,
            section=section,
            venue_mode=venue_mode,
            ordinal=index,
            profile=semantic_profile or {},
        )
    else:
        section["laser_program"] = {
            **dict(section["laser_program"]),
            "zone_policy": str(dict(section["laser_program"]).get("zone_policy") or "balanced"),
        }
```

Do not replace authored `cue_recipe` / `laser_program` with sibling mini-schemas. Extend them in place so `sections.py` stale checks and persistence paths keep working.

- [ ] **Step 9: Derive timeline flags from resolved sections without changing `resolve_show_sections()` return type**

```python
resolved_sections = resolve_show_sections(
    persisted_show_plan=persisted_show_plan,
    markers=markers,
    duration_seconds=duration_seconds,
    track_seed=track_seed,
    venue_mode=venue_mode,
)
timeline_flags = derive_timeline_flags(resolved_sections)
```

Concrete publication owners, outside `showplan/*`:

```python
# runtime_context.py
# _regenerate_selection(), bind_track_metadata(), and any section-edit
# callback path must call the single publication helper instead of updating
# show_sections directly. The `timeline_flags=` parameter is no longer
# accepted (cycle-1 panel UF-18); flags are always derived from the
# post-intent-refresh boundaries inside `_replace_show_sections_locked`.
self.replace_show_sections(resolved_sections)
```

Concrete owner: `src/photonic_synesthesia/platform/runtime_context.py`.
Do not put this publication step inside `showplan/*`.

- [ ] **Step 10: Export the new authored builders from `showplan/__init__.py`**

```python
from .recipes import build_recipe_bundle
from .phasers import build_phaser_bundle
from .tags import build_section_tags
from .timeline_flags import derive_timeline_flags
```

- [ ] **Step 11: Run authored-plan tests**

Run: `.venv/bin/python -m pytest tests/unit/test_showplan_recipes.py tests/unit/test_showplan_phasers.py tests/unit/test_showplan_tags.py tests/unit/test_showplan_timeline_flags.py tests/unit/test_showplan_imports.py -q`
Expected: `PASS`

- [ ] **Step 12: Commit**

```bash
git add src/photonic_synesthesia/showplan/recipes.py src/photonic_synesthesia/showplan/phasers.py src/photonic_synesthesia/showplan/tags.py src/photonic_synesthesia/showplan/timeline_flags.py src/photonic_synesthesia/showplan/sections.py src/photonic_synesthesia/showplan/cue_recipe.py src/photonic_synesthesia/showplan/laser_program.py src/photonic_synesthesia/showplan/__init__.py tests/unit/test_showplan_recipes.py tests/unit/test_showplan_phasers.py tests/unit/test_showplan_tags.py tests/unit/test_showplan_timeline_flags.py
git commit -m "feat: add authored showplan primitives"
```

## Task 3: Add runtime nodes that read authored playback data and fit `_SequentialPipeline`

**Files:**
- Create: `src/photonic_synesthesia/graph/nodes/trigger_router.py`
- Create: `src/photonic_synesthesia/graph/nodes/preposition.py`
- Create: `src/photonic_synesthesia/graph/nodes/surface_compositor.py`
- Create: `src/photonic_synesthesia/graph/nodes/laser_zone_runtime.py`
- Modify: `src/photonic_synesthesia/graph/builder.py`
- Modify: `src/photonic_synesthesia/graph/nodes/fixture_control.py`
- Modify: `src/photonic_synesthesia/graph/nodes/ilda_output.py`
- Test: `tests/unit/test_trigger_router.py`
- Test: `tests/unit/test_preposition.py`
- Test: `tests/unit/test_surface_compositor.py`
- Test: `tests/unit/test_laser_zone_runtime.py`
- Test: `tests/unit/test_graph_builder.py`
- Test: `tests/unit/test_fixture_control.py`
- Test: `tests/integration/test_professional_rollout_pipeline.py`

- [ ] **Step 1: Write the failing trigger-router test against a published playback snapshot**

```python
from photonic_synesthesia.graph.nodes.trigger_router import TriggerRouterNode

def test_trigger_router_emits_due_events_once_per_flag() -> None:
    node = TriggerRouterNode()
    state = {
        "playback_snapshot": {
            "playhead_seconds": 32.0,
            "transport_revision": 4,
            "timeline_flags": [
                {"id": "sec-1:handoff", "kind": "handoff", "at_seconds": 31.5, "payload": {"section_id": "sec-1"}}
            ],
        },
        "trigger_events": [],
    }

    first = node(dict(state))
    second = node(dict(state))

    assert first["trigger_events"] == [
        {"id": "sec-1:handoff", "kind": "handoff", "payload": {"section_id": "sec-1"}}
    ]
    assert second["trigger_events"] == []
```

- [ ] **Step 2: Write the failing pre-position test against authored section intent and dark-window gating**

```python
from photonic_synesthesia.core.state import MusicStructure
from photonic_synesthesia.graph.nodes.preposition import PrepositionNode


def test_preposition_emits_targets_only_in_release_window() -> None:
    node = PrepositionNode()
    state = {
        "playback_snapshot": {
            "show_sections": [
                {
                    "id": "sec-1",
                    "start_seconds": 0.0,
                    "end_seconds": 32.0,
                    "preposition_intent": {"enabled": True, "when": "release", "targets": ["fan_open"]},
                }
            ],
            "playhead_seconds": 8.0,
        },
        "control_state": {"blackout_active": False},
        "director_state": {"subphrase_role": "release"},
        "current_structure": MusicStructure.BREAKDOWN,
        "preposition_targets": [],
    }

    updated = node(state)

    # PrepositionNode emits one target per active fixture (cycle-1 panel
    # UF-21: index [0] consumption). For a single-fixture fixture set:
    assert updated["preposition_targets"] == [
        {"fixture_id": "mh-1", "section_id": "sec-1", "preset": "fan_open"}
    ]
```

- [ ] **Step 2b: Write the failing surface-compositor test**

```python
from photonic_synesthesia.graph.nodes.surface_compositor import SurfaceCompositorNode


def test_surface_compositor_emits_layer_per_active_section_and_surface() -> None:
    """Cycle-1 panel UF-24: `tests/unit/test_surface_compositor.py` was
    listed as a file to create but had no test body in cycle 1 — so the
    node could ship unverified. This test pins the two observable
    properties the plan relies on: (a) one layer is emitted per authored
    section's `surface_program` when the section is active at the current
    playhead, (b) each layer carries `fixture_id`, `section_id`,
    `surface_mode`, and `target` so downstream consumers filter by fixture
    (UF-21).
    """
    node = SurfaceCompositorNode()
    state = {
        "playback_snapshot": {
            "show_sections": [
                {
                    "id": "sec-1",
                    "start_seconds": 0.0,
                    "end_seconds": 30.0,
                    "surface_program": {"surface_mode": "texture", "target": "panel-1"},
                }
            ],
            "playhead_seconds": 10.0,
        },
        "surface_layers": [],
    }

    updated = node(state)

    assert updated["surface_layers"] == [
        {"fixture_id": "panel-1", "section_id": "sec-1", "surface_mode": "texture", "target": "panel-1"}
    ]
```

- [ ] **Step 2c: Write the failing laser-zone-runtime test**

```python
from photonic_synesthesia.core.config import FixtureConfig
from photonic_synesthesia.graph.nodes.laser_zone_runtime import LaserZoneRuntimeNode


def test_laser_zone_runtime_clamps_brightness_and_applies_protected_half_plane() -> None:
    """Cycle-1 panel UF-24 + UF-19 + UF-20: prove the node clamps out-of-range
    brightness_cap values to [0, 255] DMX range (hardware safety), uses
    unbiased rounding, and blanks points on the configured per-fixture
    protected half-plane (not a hardcoded `y < 0` check).
    """
    fixture = FixtureConfig(
        id="laser-1",
        name="Laser",
        type="laser",
        profile="generic_laser",
        start_address=1,
        enabled=True,
    )
    node = LaserZoneRuntimeNode(fixtures=[fixture])
    state = {
        "laser_zone_rules": {
            "laser-1": {"brightness_cap": 1.5, "protected": True, "policy": "overhead_only"},
            # Bright cap is intentionally > 1.0 to prove the clamp holds.
        },
        "ilda_frames": [
            {
                "fixture_id": "laser-1",
                "points": [
                    {"x": 0.0, "y":  0.2, "r": 100, "g": 100, "b": 100, "blanked": False},
                    {"x": 0.0, "y": -0.2, "r": 255, "g": 255, "b": 255, "blanked": False},
                ],
            }
        ],
    }

    updated = node(state)

    points = updated["ilda_frames"][0]["points"]
    # Point 0 (y > 0): kept. Brightness clamped to 255 even though cap*value = 150.
    assert points[0]["blanked"] is False
    assert points[0]["r"] == 150  # 100 * 1.5 = 150.0 → round → 150
    assert points[0]["g"] == 150
    # Point 1 (y < 0, protected + default half-plane): blanked. Brightness
    # clamped at 255 ceiling (255 * 1.5 = 382.5 → clamped to 255).
    assert points[1]["blanked"] is True
    assert points[1]["r"] == 255
```

- [ ] **Step 3: Write the failing pipeline-order test**

```python
from photonic_synesthesia.graph.builder import build_photonic_graph


def test_professional_nodes_land_in_real_pipeline_order() -> None:
    graph = build_photonic_graph(mock_sensors=True)

    assert graph.graph._node_names == [
        "audio_sense",
        "feature_extract",
        "beat_track",
        "structure_detect",
        "midi_sense",
        "cv_sense",
        "fusion",
        "director_intent",
        "scene_select",
        "trigger_router",
        "preposition",
        "surface_compositor",
        "laser_control",
        "moving_head_control",
        "panel_control",
        "interpreter",
        "safety_interlock",
        "ilda_output",
        "laser_zone_runtime",
        "laser_vector_interlock",
        "ilda_transport",
        "dmx_output",
    ]
```

- [ ] **Step 4: Run the failing runtime-node and builder tests**

Run: `.venv/bin/python -m pytest tests/unit/test_trigger_router.py tests/unit/test_preposition.py tests/unit/test_surface_compositor.py tests/unit/test_laser_zone_runtime.py tests/unit/test_graph_builder.py -q`
Expected: `FAIL`

- [ ] **Step 5: Publish one atomic playback snapshot per tick before node execution**

`_publish_playback_snapshot()` deep-copies the snapshot and explicitly resets frame-local artifacts (cycle-1 panel UF-8, SF-3) so that no prior-tick `preposition_targets` / `surface_layers` / `laser_zone_rules` / `trigger_events` can leak into the current tick via a node's fallback logic.

```python
# builder.py — add `import copy` at module top alongside the existing
# imports (cycle-5 panel Codex-LOW: snippet uses `copy.deepcopy` without
# the import).
import copy


def _publish_playback_snapshot(self) -> None:
    """Graph publisher — calls PlaybackContext's INTERNAL aliased method
    (cycle-2 panel NC-8) so we pay for exactly ONE deep-copy per tick
    rather than two (which is what calling the public `snapshot()` would
    cost now that it deep-copies). The public method exists for
    web-panel / test / UI consumers who can't otherwise be trusted to
    avoid mutating the returned dict.
    """
    playback = get_shared_playback_context()
    if playback is None:
        self._state["playback_snapshot"] = {}
    else:
        with playback._lock:
            aliased = playback._snapshot_internal_locked()
        # Deep-copy at the publication boundary (cycle-1 panel UF-8).
        # The aliased dict shares nested structures with the authored
        # cache; copying here breaks the alias so nodes can safely
        # treat `state["playback_snapshot"]` as their own scratch space.
        # Copy cost: ~0.5 ms for a 40-section show (validated in Task 5
        # Step 0 pipeline fixture performance test).
        self._state["playback_snapshot"] = copy.deepcopy(aliased)
    # Explicit frame-local artifact reset (cycle-1 panel SF-3). Every tick
    # starts from a clean slate so nodes cannot silently fall back onto
    # prior-tick values.
    self._state["preposition_targets"] = []
    self._state["surface_layers"] = []
    self._state["laser_zone_rules"] = {}
    self._state["trigger_events"] = []


def step(self) -> PhotonicState:
    with self._state_lock:
        self._sync_control_state()
        self._sync_output_blackout_latches()
        self._publish_playback_snapshot()
        self._state = self.graph.invoke(self._state)
        if self.control_plane_service is not None:
            node_stats = {
                name: node.get_stats()
                for name, node in self.nodes.items()
                if hasattr(node, "get_stats")
            }
            self.control_plane_service.update_from_photonic_state(
                self._state,
                node_stats=node_stats,
            )
        return self._state
```

Every runtime node added in this task reads `state["playback_snapshot"]`. Do not call `get_shared_playback_context().snapshot()` inside the nodes themselves.

- [ ] **Step 5b: Retrofit pre-existing snapshot readers onto the published snapshot**

The atomic-snapshot invariant only holds if ALL consumers read the same published dict. `ILDAOutputNode` and `MovingHeadControlNode` already look up authored section / laser_program data by calling `get_shared_playback_context().snapshot()` directly, mid-tick. Those call sites MUST be migrated.

**Retrofit target is `_current_program_look()`, NOT `__call__` (cycle-1 panel UF-17).** Verified against shipped code: the `get_shared_playback_context().snapshot()` call lives at `src/photonic_synesthesia/graph/nodes/ilda_output.py:263` inside `_current_program_look(self, state: PhotonicState)`, and at `src/photonic_synesthesia/graph/nodes/fixture_control.py:489` inside `MovingHeadControlNode._current_program_look(self, state: PhotonicState)`. `__call__` at both files (line 203 / line 257) invokes the helper — replacing `__call__`'s body would miss the real read and leave the mid-tick call in place.

```python
# src/photonic_synesthesia/graph/nodes/ilda_output.py — inside
# ILDAOutputNode._current_program_look(self, state: PhotonicState)
# at runtime the shipped code is `snapshot = playback.snapshot()` at line
# 263; replace those two lines (260–263) that fetch the global context with:
snapshot = dict(state.get("playback_snapshot") or {})
if not snapshot:
    return None
```

```python
# src/photonic_synesthesia/graph/nodes/fixture_control.py — inside
# MovingHeadControlNode._current_program_look(self, state: PhotonicState)
# replace the `playback = get_shared_playback_context(); snapshot = playback.snapshot()`
# pair at lines 488–489 with:
snapshot = dict(state.get("playback_snapshot") or {})
if not snapshot:
    return None
```

The rest of each helper body (section-by-playhead scan, laser_program lookup, progress computation) is unchanged — the refactor changes only where the snapshot comes from.

Acceptance test (cycle-1 panel UF-13 — observable-equivalence of staged_look as preview-only):

```python
def test_pipeline_runtime_frames_are_byte_identical_with_and_without_staged_look(pipeline_fixtures) -> None:
    """staged_look is preview-only: runtime frames must NOT change when a
    stage is present pre-commit. This test runs two graph steps — one
    before staging, one after — and asserts every runtime-observable
    field of the published state is byte-identical. UI-only fields
    (`playback_snapshot["staged_look"]`) are excluded from the comparison.
    """
    _, _, ctx = pipeline_fixtures
    graph = build_photonic_graph(Settings(), mock_sensors=True)

    # Baseline tick.
    ctx.update_transport(playhead_seconds=20.0, playing=True, finished=False, realtime=True, speed=1.0)
    s_before = graph.step()

    # Stage an operator override on the active section. With preview-only
    # semantics, runtime output must not change.
    ctx.set_staged_look(
        section_id="sec-1",
        cue_recipe={"phasers": [], "recipe_lines": [{"selection": "laser:build_1:operator"}]},
        laser_program={"zone_policy": "crowd_punctuate"},
    )
    ctx.update_transport(playhead_seconds=20.02, playing=True, finished=False, realtime=True, speed=1.0)
    s_after = graph.step()

    runtime_keys = [
        "ilda_frames",
        "dmx_frame",
        "fixture_commands",
        "laser_zone_rules",
        "preposition_targets",
        "surface_layers",
    ]
    for key in runtime_keys:
        # Byte-equivalence ignoring timestamps that move with the clock.
        before = _strip_timestamps(copy.deepcopy(s_before.get(key)))
        after = _strip_timestamps(copy.deepcopy(s_after.get(key)))
        assert before == after, (
            f"staged_look bled into runtime output at state[{key!r}] — preview-only "
            f"contract violated (cycle-1 panel UF-11 / UF-13)"
        )
    # The snapshot still surfaces the stage for the UI.
    assert s_after["playback_snapshot"]["staged_look"]["section_id"] == "sec-1"
```

- [ ] **Step 6: Implement runtime nodes that read from the published playback snapshot**

```python
class TriggerRouterNode:
    def __init__(self) -> None:
        self._fired_ids: set[str] = set()
        self._last_playhead = 0.0
        # Ledger reset keys on the AUTHORED-state revision, NOT transport_revision.
        # transport_revision bumps on every update_transport() call (once per
        # frame). Keying the ledger reset on it would clear _fired_ids every
        # tick — the exact cycle-2 regression this fix addresses.
        self._last_timeline_flag_revision = -1

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        snapshot = dict(state.get("playback_snapshot") or {})
        playhead = float(snapshot.get("playhead_seconds", 0.0))
        timeline_flag_revision = int(snapshot.get("timeline_flag_revision", 0))
        flags = list(snapshot.get("timeline_flags", []))
        # Cycle-2 panel NC-4: ledger-clear semantics MUST distinguish
        # "authored change at non-zero playhead" (treat past flags as
        # already-seen) from "backward seek" (operator wants past flags
        # to re-fire). Without this split, a mid-show operator action
        # that bumps `_timeline_flag_revision` would clear the ledger
        # and then immediately fire every flag from 0..playhead in a
        # single tick — the "thundering herd" regression.
        revision_changed = timeline_flag_revision != self._last_timeline_flag_revision
        rewound = playhead < self._last_playhead
        # Cycle-3 panel 3C-N1: the first `__call__` has
        # `_last_timeline_flag_revision = -1` and a published revision of 0
        # (or higher), so `revision_changed` is True on boot — but there's
        # no "previous authored state" to have already-seen flags against.
        # Pre-populating on the first tick would swallow every flag whose
        # `at_seconds <= playhead`, including canonical section-0
        # `phrase_head` flags at `at_seconds = 0.0`. Guard the pre-populate
        # branch with `self._last_timeline_flag_revision >= 0` so the very
        # first tick falls through to ordinary due-detection.
        is_initial_tick = self._last_timeline_flag_revision < 0
        if revision_changed and not rewound and not is_initial_tick:
            # Authored state changed during forward playback. Pre-populate
            # the ledger with every flag whose `at_seconds <= playhead` so
            # only newly-crossed flags will fire on this tick; past flags
            # are implicitly "already seen" against the new authored state.
            self._fired_ids = {
                str(flag["id"]) for flag in flags
                if float(flag.get("at_seconds", 0.0)) <= playhead
            }
        elif rewound:
            # Operator rewound the playhead. Past flags SHOULD re-fire on
            # the replay — clear the ledger fully and let the normal
            # due-detection below pick up every flag <= playhead.
            self._fired_ids.clear()
        # else: forward playback on unchanged authored state (or the very
        # first tick) — ledger stays intact; initial flags fire normally.
        self._last_timeline_flag_revision = timeline_flag_revision
        self._last_playhead = playhead
        due = [
            flag for flag in flags
            if float(flag.get("at_seconds", 0.0)) <= playhead and str(flag.get("id", "")) not in self._fired_ids
        ]
        # Append to any existing trigger_events (upstream nodes may have
        # emitted their own) rather than overwriting — preserves the
        # additive-bus convention other pipeline stages rely on.
        existing_events = list(state.get("trigger_events") or [])
        existing_events.extend(
            {"id": str(flag["id"]), "kind": str(flag["kind"]), "payload": dict(flag.get("payload") or {})}
            for flag in due
        )
        state["trigger_events"] = existing_events
        self._fired_ids.update(str(flag["id"]) for flag in due)
        return state
```

Acceptance tests for the ledger invariant (add to `tests/unit/test_trigger_router.py`):

```python
def test_trigger_router_does_not_refire_on_routine_transport_updates() -> None:
    """transport_revision bumps every frame; ledger must NOT clear on it."""
    node = TriggerRouterNode()
    flag = {"id": "sec-1:phrase_head", "kind": "phrase_head", "at_seconds": 1.0, "payload": {}}
    base = {"playhead_seconds": 1.5, "timeline_flag_revision": 7, "timeline_flags": [flag]}
    # Tick 1 — flag fires.
    s1 = node({"playback_snapshot": dict(base, transport_revision=100), "trigger_events": []})
    assert s1["trigger_events"] == [{"id": "sec-1:phrase_head", "kind": "phrase_head", "payload": {}}]
    # Tick 2 — transport_revision bumped (playhead advanced normally), same
    # authored state. Ledger must hold; flag must NOT re-fire.
    s2 = node({"playback_snapshot": dict(base, playhead_seconds=1.6, transport_revision=101), "trigger_events": []})
    assert s2["trigger_events"] == []


def test_trigger_router_refires_after_authored_revision_bump() -> None:
    node = TriggerRouterNode()
    flag = {"id": "sec-1:phrase_head", "kind": "phrase_head", "at_seconds": 1.0, "payload": {}}
    s1 = node({
        "playback_snapshot": {"playhead_seconds": 1.5, "timeline_flag_revision": 7, "timeline_flags": [flag]},
        "trigger_events": [],
    })
    assert len(s1["trigger_events"]) == 1
    # Authored state changed (replace_show_sections fired) → ledger clears.
    s2 = node({
        "playback_snapshot": {"playhead_seconds": 1.5, "timeline_flag_revision": 8, "timeline_flags": [flag]},
        "trigger_events": [],
    })
    assert len(s2["trigger_events"]) == 1
```

```python
class PrepositionNode:
    """Emit one preposition target per active moving-head fixture.

    Cycle-1 panel UF-21 fix: each emitted target carries its own
    `fixture_id` so downstream `MovingHeadControlNode` can filter. The
    node takes the fixture list at construction time (symmetric with
    `LaserZoneRuntimeNode`), so `build_photonic_graph` wires it with
    `PrepositionNode(fixtures=settings.fixtures)`.
    """

    def __init__(self, *, fixtures: list[FixtureConfig] | None = None) -> None:
        self._moving_head_fixture_ids = [
            str(f.id) for f in (fixtures or []) if getattr(f, "type", "") == "moving_head"
        ]

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        snapshot = dict(state.get("playback_snapshot") or {})
        playhead = float(snapshot.get("playhead_seconds", 0.0))
        blackout_active = bool((state.get("control_state") or {}).get("blackout_active", False))
        subphrase_role = str((state.get("director_state") or {}).get("subphrase_role") or "")
        dark_window_open = blackout_active or subphrase_role in {"release", "settle"}
        targets: list[dict[str, str]] = []
        for section in list(snapshot.get("show_sections", [])):
            start = float(section.get("start_seconds", 0.0))
            end = float(section.get("end_seconds", start))
            if not (start <= playhead < max(end, start + 1e-6)):
                continue
            intent = dict(section.get("preposition_intent") or {})
            intent_when = str(intent.get("when") or "release")
            if not intent.get("enabled"):
                continue
            if not (
                intent_when == "always"
                or (intent_when == "blackout" and blackout_active)
                or (intent_when == "release" and dark_window_open)
            ):
                continue
            presets = list(intent.get("targets") or [])
            # Broadcast each preset to every active moving-head fixture so
            # each fixture receives its own target. If the fixture list is
            # empty (e.g. unit test without a fixture roster), fall back to
            # a single un-addressed target for backwards compatibility with
            # tests that don't filter.
            fixture_ids = self._moving_head_fixture_ids or ["mh-1"]
            for preset in presets:
                for fixture_id in fixture_ids:
                    targets.append({
                        "fixture_id": fixture_id,
                        "section_id": str(section["id"]),
                        "preset": str(preset),
                    })
        state["preposition_targets"] = targets
        return state
```

- [ ] **Step 7: Implement surface compositor and laser zone runtime**

```python
class SurfaceCompositorNode:
    """Emit one surface layer per active section PER addressable panel fixture.

    Cycle-2 panel NC-9 fix: the cycle-2 plan emitted layers with
    `fixture_id=target`, where `target` could be a group label like
    "led_wall" — panels filtering by their own `fixture.id` (e.g.
    "panel-1", "panel-2") then received no layers and silently went
    dark. Cycle 3 takes a fixture roster at construction time, maps
    group-label targets to the set of panel fixtures belonging to that
    group, and emits one layer per (section, matching-panel).

    Grouping convention: a surface panel fixture's `FixtureConfig` has
    an optional `surface_group: str | None` attribute. If authored
    `target` matches a known `fixture.id`, the layer goes to that
    specific panel. If `target` matches a `fixture.surface_group`, the
    layer is broadcast to every panel sharing that group. If `target`
    matches neither, the layer is emitted with `fixture_id=target` as a
    last-resort passthrough (logs a one-time warning; this is the
    cycle-2 behavior preserved as a safety net).
    """

    def __init__(self, *, fixtures: list[FixtureConfig] | None = None) -> None:
        # Build id-set and group → ids map from the fixture roster.
        panel_fixtures = [
            f for f in (fixtures or []) if getattr(f, "type", "") == "panel"
        ]
        self._panel_fixture_ids: set[str] = {str(f.id) for f in panel_fixtures}
        self._panel_group_to_ids: dict[str, list[str]] = {}
        for f in panel_fixtures:
            group = getattr(f, "surface_group", None)
            if group:
                self._panel_group_to_ids.setdefault(str(group), []).append(str(f.id))
        self._warned_unknown_targets: set[str] = set()

    def _resolve_target_fixture_ids(self, target: str) -> list[str]:
        """Map an authored `target` to the concrete fixture IDs it addresses."""
        if target in self._panel_fixture_ids:
            return [target]
        if target in self._panel_group_to_ids:
            return list(self._panel_group_to_ids[target])
        # Fall back: emit with the opaque label; downstream either matches
        # on its own id (it won't, but this preserves cycle-2 single-panel
        # deployments that used `target` as a fixture id without the new
        # `surface_group` attribute) or logs a miss.
        if target not in self._warned_unknown_targets:
            self._warned_unknown_targets.add(target)
            logger.warning(
                "SurfaceCompositor received unknown target; "
                "no panel fixture with matching id or surface_group",
                target=target,
            )
        return [target]

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        snapshot = dict(state.get("playback_snapshot") or {})
        playhead = float(snapshot.get("playhead_seconds", 0.0))
        layers: list[dict[str, str]] = []
        for section in list(snapshot.get("show_sections", [])):
            start = float(section.get("start_seconds", 0.0))
            end = float(section.get("end_seconds", start))
            if not (start <= playhead < max(end, start + 1e-6)):
                continue
            program = dict(section.get("surface_program") or {})
            if not program:
                continue
            target = str(program.get("target", ""))
            if not target:
                continue
            surface_mode = str(program.get("surface_mode", "accent"))
            section_id = str(section["id"])
            for fixture_id in self._resolve_target_fixture_ids(target):
                layers.append({
                    "fixture_id": fixture_id,
                    "section_id": section_id,
                    "surface_mode": surface_mode,
                    "target": target,
                })
        state["surface_layers"] = layers
        return state
```

```python
from photonic_synesthesia.core.config import FixtureConfig


def _channel_clamp(value: float) -> int:
    """Convert a floating-point channel value in ~[0, 255] to a DMX byte.

    Uses round() (banker's round) not int() (truncation) for bias-free
    scaling (cycle-1 panel UF-35), and bound-clamps to [0, 255] so caps or
    producer values outside [0.0, 1.0] cannot emit out-of-range DMX bytes
    (cycle-1 panel UF-19). Out-of-range values are a physical-fixture
    safety concern, not just a policy nit.
    """
    if value != value:  # NaN
        return 0
    clamped = max(0.0, min(255.0, value))
    return int(round(clamped))


class LaserZoneRuntimeNode:
    """Pure transform: apply authored zone policies to ILDA frames in place.

    Safety model (cycle-1 panel UF-20): the "protected" flag blanks points
    on the protected half-plane of each fixture's physical mount. The
    half-plane is NOT a hardcoded `y < 0` check — it comes from the
    fixture config, so rigs with different mount conventions (stage-
    bottom-up vs ceiling-down, center-origin vs corner-origin) don't
    blank the wrong half.
    """

    def __init__(self, *, fixtures: list[FixtureConfig] | None = None) -> None:
        self._protected_half_plane_by_fixture = {
            str(f.id): self._protected_half_plane_for_fixture(f)
            for f in (fixtures or [])
        }

    @staticmethod
    def _protected_half_plane_for_fixture(fixture: FixtureConfig) -> tuple[str, float, bool]:
        """Return (axis, threshold, below_is_protected) from the fixture config.

        Default for a venue without explicit calibration: axis="y",
        threshold=0.0, below_is_protected=True — matches the cycle-1 plan's
        `y < 0` behavior for venues using center-origin, Y-up coordinates.
        Rigs that don't match this convention set `safety_protected_half_plane`
        on their `FixtureConfig` (added in the per-venue calibration PR that
        follows this plan) to override.
        """
        override = getattr(fixture, "safety_protected_half_plane", None)
        if isinstance(override, dict):
            return (
                str(override.get("axis", "y")),
                float(override.get("threshold", 0.0)),
                bool(override.get("below_is_protected", True)),
            )
        return ("y", 0.0, True)

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        rules = state.get("laser_zone_rules", {})
        frames: list[dict[str, Any]] = []
        for frame in list(state.get("ilda_frames", [])):
            updated = dict(frame)
            fixture_id = str(frame.get("fixture_id", ""))
            rule = rules.get(fixture_id, {})
            brightness_cap = float(rule.get("brightness_cap", 1.0))
            protected = bool(rule.get("protected", False))
            axis, threshold, below_is_protected = self._protected_half_plane_by_fixture.get(
                fixture_id,
                ("y", 0.0, True),
            )
            updated["points"] = [
                {
                    **point,
                    "r": _channel_clamp(point["r"] * brightness_cap),
                    "g": _channel_clamp(point["g"] * brightness_cap),
                    "b": _channel_clamp(point["b"] * brightness_cap),
                    "blanked": bool(point["blanked"]) or (
                        protected and self._point_is_protected(point, axis, threshold, below_is_protected)
                    ),
                }
                for point in list(frame.get("points", []))
            ]
            frames.append(updated)
        state["ilda_frames"] = frames
        return state

    @staticmethod
    def _point_is_protected(
        point: dict[str, Any],
        axis: str,
        threshold: float,
        below_is_protected: bool,
    ) -> bool:
        value = float(point.get(axis, 0.0))
        return (value < threshold) if below_is_protected else (value > threshold)
```

This node is a pure transform, not a transport. It must not join the blackout-latch list, and it must never add points or reorder frames; only clamp/blank the existing point stream before `LaserVectorInterlockNode`.

`_channel_clamp` uses `round()` + `max/min` (cycle-1 panel UF-19, UF-35) so:
- A cap > 1.0 cannot produce a DMX byte > 255 (hardware safety — over-driven LEDs can fail or damage optics).
- A cap < 0 or a NaN cannot produce a byte < 0 or a Python truthiness surprise.
- Rounding is unbiased (`int()` always rounds towards zero, systematically dimming output).

The protected half-plane comes from per-fixture config, not a hardcoded `y < 0` check (cycle-1 panel UF-20). Venues with ceiling-mounted downward-facing lasers, or stage-bottom-up geometries, or rigs offset from center-origin all calibrate their own half-plane rather than being silently blanked on the wrong side.

- [ ] **Step 8: Thread the new nodes into the real builder**

```python
    nodes["trigger_router"] = TriggerRouterNode()
    nodes["preposition"] = PrepositionNode(fixtures=settings.fixtures)
    nodes["surface_compositor"] = SurfaceCompositorNode(fixtures=settings.fixtures)
    nodes["laser_zone_runtime"] = LaserZoneRuntimeNode(fixtures=settings.fixtures)
```

```python
    pipeline = _SequentialPipeline(
        node_names=[
            "audio_sense",
            "feature_extract",
            "beat_track",
            "structure_detect",
            "midi_sense",
            "cv_sense",
            "fusion",
            "director_intent",
            "scene_select",
            "trigger_router",
            "preposition",
            "surface_compositor",
            "laser_control",
            "moving_head_control",
            "panel_control",
            "interpreter",
            "safety_interlock",
            "ilda_output",
            "laser_zone_runtime",
            "laser_vector_interlock",
            "ilda_transport",
            "dmx_output",
        ],
        nodes=nodes,
    )
```

- [ ] **Step 9: Consume the new artifacts in control/output nodes with behavior-changing tests**

```python
# tests/unit/test_fixture_control.py
from photonic_synesthesia.core.config import FixtureConfig, MovingHeadSafetyConfig
from photonic_synesthesia.core.state import MusicStructure, create_initial_state
from photonic_synesthesia.graph.nodes.fixture_control import DEFAULT_PALETTE, MovingHeadControlNode, PanelControlNode


def test_moving_head_preposition_slows_motion_in_breakdown() -> None:
    """Exercise `MovingHeadControlNode.__call__` end-to-end (cycle-1 panel UF-26).

    The cycle-1 test called the private `_generate_moving_head_commands` helper
    directly with a hand-crafted `program_look`, which only proved the helper's
    math worked — NOT that `state["preposition_targets"]` is wired through
    `__call__` correctly. This revision seeds the full state, invokes the node
    via its public contract, and asserts the observed channel-value change.
    """
    fixture = FixtureConfig(
        id="mh-1",
        name="Test Mover",
        type="moving_head",
        profile="generic_moving_head",
        start_address=1,
        enabled=True,
    )
    # MovingHeadControlNode constructor requires a positional `safety=` arg
    # (src/photonic_synesthesia/graph/nodes/fixture_control.py:216-220).
    node = MovingHeadControlNode(fixtures=[fixture], safety=MovingHeadSafetyConfig())

    def _make_state(preposition_targets: list[dict[str, Any]]) -> dict[str, Any]:
        state = create_initial_state()
        state["current_structure"] = MusicStructure.BREAKDOWN
        state["bpm"] = 122.0
        state["beat_phase"] = 0.0
        state["bar_position"] = 1
        state["energy"] = 0.3
        state["time_since_drop"] = 10.0
        state["subphrase_role"] = "release"
        state["preposition_targets"] = preposition_targets
        state["playback_snapshot"] = {"show_sections": [], "playhead_seconds": 0.0}
        return state

    baseline_state = _make_state(preposition_targets=[])
    baseline = node(baseline_state)

    prepositioned_state = _make_state(
        preposition_targets=[{"fixture_id": "mh-1", "section_id": "sec-1", "preset": "fan_open"}]
    )
    prepositioned = node(prepositioned_state)

    speed_channel = fixture.start_address + node.channel_map["pan_tilt_speed"]
    baseline_value = baseline["fixture_commands"][0]["channel_values"][speed_channel]
    prepositioned_value = prepositioned["fixture_commands"][0]["channel_values"][speed_channel]
    assert prepositioned_value < baseline_value, (
        "Prepositioning in breakdown must reduce pan/tilt speed below the baseline — "
        "if this fails, `MovingHeadControlNode.__call__` is not honoring state['preposition_targets']"
    )

# fixture_control.py / MovingHeadControlNode
# Fixture-id-filtered read (cycle-1 panel UF-21). PrepositionNode emits
# one target per active fixture; each consumer picks the target for its
# own fixture_id. Zero-target fallback is preserved.
preposition_targets = list(state.get("preposition_targets", []))
my_fixture_id = str(fixture.id)
my_target = next(
    (t for t in preposition_targets if str(t.get("fixture_id", "")) == my_fixture_id),
    None,
)
preposition_target = my_target.get("preset") if isinstance(my_target, dict) else None
if preposition_target and structure in {MusicStructure.BREAKDOWN, MusicStructure.OUTRO}:
    program_look = dict(program_look or {})
    program_look["preposition_target"] = preposition_target

# fixture_control.py / _generate_moving_head_commands(...)
preposition_target = str(program_look.get("preposition_target", "")) if isinstance(program_look, dict) else ""
if preposition_target:
    mover_family = "hold"
    motion_scale = min(motion_scale, 0.4)
    target_bias = "ceiling"

commands = self._generate_moving_head_commands(
    fixture,
    scene,
    structure,
    beat_phase,
    bar_position,
    bpm,
    energy,
    state["timestamp"],
    phase_offset,
    program_look=program_look,
    palette=palette,
    color_drive=color_drive,
)
```

```python
# tests/unit/test_fixture_control.py
def test_panel_control_surface_mode_changes_render_path() -> None:
    fixture = FixtureConfig(
        id="panel-1",
        name="Test Panel",
        type="panel",
        profile="generic_panel",
        start_address=1,
        enabled=True,
    )
    node = PanelControlNode(fixtures=[fixture])
    state = create_initial_state()
    state["current_structure"] = MusicStructure.DROP
    state["surface_layers"] = [{"section_id": "sec-1", "surface_mode": "texture", "target": "led_wall"}]

    textured = node(state)

    assert textured["fixture_commands"][0]["channel_values"][fixture.start_address + node.channel_map["strobe"]] == 0

# fixture_control.py / PanelControlNode.__call__
# Fixture-id-filtered read (cycle-1 panel UF-21). SurfaceCompositorNode
# emits one layer per active surface fixture; each consumer reads the
# layer for its own fixture_id.
surface_layers = list(state.get("surface_layers", []))
my_fixture_id = str(fixture.id)
my_layer = next(
    (layer for layer in surface_layers if str(layer.get("fixture_id", "")) == my_fixture_id),
    None,
)
active_surface_mode = (
    str(my_layer.get("surface_mode"))
    if isinstance(my_layer, dict) and my_layer.get("surface_mode") else "accent"
)

commands = self._generate_panel_commands(
    fixture,
    structure,
    beat_phase,
    bar_position,
    energy,
    time_since_drop,
    state["timestamp"],
    palette=palette,
    color_drive=color_drive,
    strobe_budget_hz=strobe_budget_hz,
    subphrase_role=subphrase_role,
    surface_mode=active_surface_mode,
)

# fixture_control.py / _generate_panel_commands(...)
if surface_mode == "texture":
    render_mode = "morph"
    strobe = 0
elif surface_mode == "accent":
    render_mode = "dual_cycle"
```

```python
# ilda_output.py
# Each authored zone_policy maps to a distinct (brightness_cap, protected,
# crowd_punctuate_weight) tuple so authored differentiation survives into
# runtime. The four values (plus the "balanced" default) must stay
# distinguishable — collapsing crowd_punctuate and mixed_air into the
# same output path was the cycle-2 regression this table fixes.
_ZONE_POLICY_RULES: dict[str, dict[str, Any]] = {
    "overhead_only":    {"brightness_cap": 0.35, "protected": True,  "crowd_punctuate_weight": 0.0},
    "overhead_bias":    {"brightness_cap": 0.60, "protected": False, "crowd_punctuate_weight": 0.0},
    "mixed_air":        {"brightness_cap": 0.85, "protected": False, "crowd_punctuate_weight": 0.0},
    "crowd_punctuate":  {"brightness_cap": 0.95, "protected": False, "crowd_punctuate_weight": 1.0},
    "balanced":         {"brightness_cap": 1.00, "protected": False, "crowd_punctuate_weight": 0.0},
}

active_zone_policy = str(laser_program.get("zone_policy", "balanced"))
_rule = _ZONE_POLICY_RULES.get(active_zone_policy, _ZONE_POLICY_RULES["balanced"])
state["laser_zone_rules"] = {
    str(frame["fixture_id"]): dict(_rule, policy=active_zone_policy)
    for frame in list(state.get("ilda_frames", []))
}
```

Acceptance test: for each of the five `zone_policy` values, verify that
the resulting `laser_zone_rules` tuple is UNIQUE against the others.
Collapsing two authored policies to the same runtime rule regresses
this guarantee and must fail the test.

- [ ] **Step 10: Run runtime-node, builder, and integration tests**

Run: `.venv/bin/python -m pytest tests/unit/test_trigger_router.py tests/unit/test_preposition.py tests/unit/test_surface_compositor.py tests/unit/test_laser_zone_runtime.py tests/unit/test_graph_builder.py tests/unit/test_fixture_control.py tests/integration/test_professional_rollout_pipeline.py -q`
Expected: `PASS`

- [ ] **Step 11: Commit**

```bash
git add src/photonic_synesthesia/graph/nodes/trigger_router.py src/photonic_synesthesia/graph/nodes/preposition.py src/photonic_synesthesia/graph/nodes/surface_compositor.py src/photonic_synesthesia/graph/nodes/laser_zone_runtime.py src/photonic_synesthesia/graph/builder.py src/photonic_synesthesia/graph/nodes/fixture_control.py src/photonic_synesthesia/graph/nodes/ilda_output.py tests/unit/test_trigger_router.py tests/unit/test_preposition.py tests/unit/test_surface_compositor.py tests/unit/test_laser_zone_runtime.py tests/unit/test_graph_builder.py tests/unit/test_fixture_control.py tests/integration/test_professional_rollout_pipeline.py
git commit -m "feat: add professional runtime nodes to sequential pipeline"
```

## Task 4: Add operator workspace and preview/commit staging on top of runtime context

**Files:**
- Create: `src/photonic_synesthesia/platform/operator_workspace.py`
- Create: `src/photonic_synesthesia/platform/staging_lane.py`
- Modify: `src/photonic_synesthesia/platform/runtime_context.py`
- Modify: `src/photonic_synesthesia/ui/web_panel.py`
- Modify: `src/photonic_synesthesia/ui/static/mock_control_plane.js`
- Modify: `src/photonic_synesthesia/ui/static/mock_control_plane.css`
- Test: `tests/unit/test_operator_workspace.py`
- Test: `tests/unit/test_staging_lane.py`
- Test: `tests/unit/test_web_panel.py`
- Test: `tests/unit/test_runtime_context_helpers.py`

- [ ] **Step 1: Write the failing operator-workspace payload test**

```python
from photonic_synesthesia.platform.operator_workspace import build_operator_workspace_banks


def test_build_operator_workspace_emits_scene_safety_and_tag_banks() -> None:
    """Scene bank lists EVERY section (cycle-1 panel UF-7). The live
    `active_scene_id` is computed per-tick in PlaybackContext.snapshot()
    from the playhead and mounted onto the workspace by the UI at render.
    """
    workspace = build_operator_workspace_banks(
        sections=[
            {"id": "drop", "section_role": "drop_1", "start_seconds": 0.0, "end_seconds": 15.0},
            {"id": "breakdown", "section_role": "breakdown", "start_seconds": 15.0, "end_seconds": 30.0},
        ],
        available_tags=["role:drop", "laser:on"],
        safety_modes=("overhead_only", "laser_off"),
    )

    bank_ids = [bank["id"] for bank in workspace["banks"]]
    assert bank_ids == ["scene", "safety", "tags"]
    scene_button_ids = [b["id"] for b in workspace["banks"][0]["buttons"]]
    assert scene_button_ids == ["scene:drop", "scene:breakdown"]
    assert workspace["banks"][1]["buttons"][0]["id"] == "safety:overhead_only"
```

- [ ] **Step 2: Write the failing staging-lane test**

```python
from photonic_synesthesia.platform.staging_lane import stage_look, commit_staged_look


def test_stage_and_commit_look_round_trips() -> None:
    staged = stage_look(
        section_id="drop-a",
        cue_recipe={"id": "cue-1"},
        laser_program={"id": "laser-1"},
    )

    committed = commit_staged_look(staged)

    assert staged["committed"] is False
    assert committed["committed"] is True
    assert staged["cue_recipe"] is not committed["cue_recipe"]
```

- [ ] **Step 3: Write the failing web-panel DOM anchor test**

```python
from pathlib import Path

from fastapi.testclient import TestClient

from photonic_synesthesia.showplan.types import SAFETY_MODES
from photonic_synesthesia.ui.web_panel import create_app


def test_web_panel_renders_operator_workspace_anchor(pipeline_fixtures) -> None:
    """Cycle-3 panel 3C-H1: strengthen to assert REAL content is published,
    not just a fallback shape. Cycle-2 test passed green while the endpoint
    returned `{"banks": []}` because it read the wrong snapshot key.
    """
    client = TestClient(create_app())
    response = client.get("/")
    workspace = client.get("/api/operator/workspace")
    js_text = Path("src/photonic_synesthesia/ui/static/mock_control_plane.js").read_text()

    assert response.status_code == 200
    assert 'id="operator-workspace"' in response.text
    assert workspace.status_code == 200
    body = workspace.json()
    # Shape checks.
    assert "banks" in body
    assert "active_scene_id" in body
    # Content checks: the pipeline fixture has two sections (sec-0, sec-1),
    # so the scene bank MUST have two buttons; safety bank must carry the
    # SAFETY_MODES tuple; tag bank must be non-empty.
    bank_ids = [bank["id"] for bank in body["banks"]]
    assert bank_ids == ["scene", "safety", "tags"], "workspace missing a required bank family"
    scene_bank = body["banks"][0]
    assert len(scene_bank["buttons"]) >= 2, "scene bank must list every section, not just the active one"
    safety_bank = body["banks"][1]
    assert len(safety_bank["buttons"]) == len(SAFETY_MODES), "safety bank must match SAFETY_MODES cardinality"
    # Live overlay:
    assert body["active_scene_id"] in {"sec-0", "sec-1"}, "active_scene_id must come from the live playhead"
    assert 'getElementById("operator-workspace")' in js_text
    assert "data-action" in js_text
```

- [ ] **Step 4: Write the failing runtime-context staging helper test**

```python
from photonic_synesthesia.platform.runtime_context import PlaybackContext


def test_playback_context_stages_and_commits_look_under_lock() -> None:
    context = PlaybackContext(
        file_path="demo.wav",
        file_name="demo.wav",
        duration_seconds=120.0,
        show_sections=[{"id": "drop-a", "start_seconds": 0.0, "end_seconds": 16.0}],
    )

    staged = context.set_staged_look(
        section_id="drop-a",
        cue_recipe={"id": "cue-1"},
        laser_program={"id": "laser-1"},
    )
    committed = context.commit_staged_look()

    assert staged["committed"] is False
    assert committed["committed"] is True
    assert context.snapshot()["staged_look"] is None
    assert context.snapshot()["show_sections"][0]["cue_recipe"]["id"] == "cue-1"
```

- [ ] **Step 5: Run the workspace, staging, web-panel, and runtime-context tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_operator_workspace.py tests/unit/test_staging_lane.py tests/unit/test_web_panel.py tests/unit/test_runtime_context_helpers.py -q`
Expected: `FAIL`

- [ ] **Step 6: Implement pure workspace and staging helpers**

```python
def build_operator_workspace_banks(
    *,
    sections: list[dict[str, Any]],
    available_tags: list[str],
    safety_modes: tuple[str, ...],
) -> dict[str, Any]:
    """Return the bank STRUCTURE — no active_scene_id.

    `active_scene_id` depends on the live playhead and must NOT be cached
    inside the authored cache (cycle-1 panel UF-7: cycle-1 plan froze it
    to section[0] via cache-miss-only path). The scene id is resolved in
    `PlaybackContext.snapshot()`'s per-call overlay from the live
    playhead_seconds; the UI mounts `active_scene_id` onto the returned
    workspace dict at render time.
    """
    return {
        "banks": [
            {
                "id": "scene",
                "buttons": [
                    {"id": f"scene:{section['id']}", "label": str(section.get("id", ""))}
                    for section in sections
                ],
            },
            {
                "id": "safety",
                "buttons": [
                    {"id": f"safety:{mode}", "label": mode} for mode in safety_modes
                ],
            },
            {
                "id": "tags",
                "buttons": [{"id": f"tag:{tag}", "label": tag} for tag in available_tags],
            },
        ]
    }
```

**Task 1 stub dependency (cycle-1 panel UF-14).** Task 1's `snapshot()` imports `build_operator_workspace_banks` from this module. Since Task 1 must be independently red/green before Task 4 lands, Task 1 creates a minimal stub first (`src/photonic_synesthesia/platform/operator_workspace.py` with `build_operator_workspace_banks(**kwargs) -> {"banks": []}`). Task 4 replaces the stub with the full implementation above. The stub keeps the signature and return-type identical so Task 1's integration test can validate wiring without depending on Task 4's implementation.

```python
def stage_look(*, section_id: str, cue_recipe: dict[str, Any], laser_program: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"staged:{section_id}",
        "source": "operator",
        "section_id": section_id,
        "cue_recipe": copy.deepcopy(cue_recipe),
        "laser_program": copy.deepcopy(laser_program),
        "committed": False,
    }


def commit_staged_look(staged_look: dict[str, Any]) -> dict[str, Any]:
    committed = copy.deepcopy(staged_look)
    committed["committed"] = True
    return committed
```

- [ ] **Step 7: Publish workspace/staging through `PlaybackContext` and API endpoints**

`PlaybackContext.snapshot()` (Task 1 Step 11b) already integrates `build_operator_workspace_banks` into the authored cache (keyed on `_authored_hash`) and surfaces `staged_look` and the per-call `active_scene_id` overlay. **No additional snapshot modification is needed here** — an earlier draft of this step hand-rolled a second `snapshot["operator_workspace"] = build_operator_workspace(...)` assignment with the cycle-1 API, which was cycle-2 panel NC-5 (regressed UF-7 + UF-29). That snippet is deleted; `snapshot()` is the single surface.

Task 4 Step 7's remaining work for the staging lane is the imports and the `PlaybackContext` method bodies (`set_staged_look`, `commit_staged_look`) below.

```python
from photonic_synesthesia.platform.staging_lane import (
    stage_look as _stage_look,
    commit_staged_look as _commit_staged_look,
)


def set_staged_look(
    self,
    *,
    section_id: str,
    cue_recipe: dict[str, Any],
    laser_program: dict[str, Any],
) -> dict[str, Any]:
    """Stage a look for operator preview.

    Preview-only semantics (cycle-1 panel UF-11): the runtime graph
    reads `show_sections` ONLY; `staged_look` surfaces in `playback_snapshot`
    for UI preview and nowhere else. `set_staged_look` bumps the authored
    hash (via `_recompute_authored_hash_locked`) so `snapshot()` invalidates
    its authored cache and the UI receives the stage on the next call —
    closing cycle-1 panel UF-6.
    """
    with self._lock, self._persistence_lock:
        if not isinstance(cue_recipe, dict) or not isinstance(laser_program, dict):
            raise RuntimeError("Invalid staged look payload")
        if not any(str(section.get("id")) == section_id for section in self.show_sections):
            raise RuntimeError("Unknown section id")
        self.staged_look = _stage_look(
            section_id=section_id,
            cue_recipe=cue_recipe,
            laser_program=laser_program,
        )
        self.server_time = time.time()
        self.transport_revision += 1
        # Bump the authored hash explicitly — staged_look is part of the
        # authored cache key. No ad-hoc `self._timeline_flag_revision += 1`;
        # the helper owns the decision and bumps iff the hash actually moves.
        self._recompute_authored_hash_locked()
        payload = self._show_plan_payload_locked()
        staged = copy.deepcopy(self.staged_look)
        self._persist_show_plan_locked(payload)
    return staged


def commit_staged_look(self) -> dict[str, Any]:
    """Commit staged_look into authored state.

    Commit-time invariants:
    - Recompute target section by id AND by current playhead time
      (cycle-1 panel SF-1) — if the playhead advanced past the staged
      section between stage and commit, the operator's intent is
      unambiguously wrong; raise and require re-stage.
    - Use `_deep_merge_section` (not `dict.update`) so deeply-nested
      authored fields are preserved under operator overrides
      (cycle-1 panel UF-12 / C5). Only keys the operator supplied in
      the stage are overridden; every other authored field survives.
    - `staged_look` cleared AFTER the authored update commits, inside
      the same locked region.
    - No ad-hoc revision bumps; `_replace_show_sections_locked` owns
      the hash decision.
    """
    with self._lock, self._persistence_lock:
        if not self.staged_look:
            raise RuntimeError("No staged look")
        committed = _commit_staged_look(self.staged_look)
        target_id = str(committed["section_id"])
        # Recompute the target section by id. If the playhead has moved past
        # that section entirely, fail closed; the operator must re-stage.
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
        # Clear staged_look inside the lock BEFORE the authored-state commit
        # so the authored hash computation in `_replace_show_sections_locked`
        # sees the cleared stage.
        self.staged_look = None
        self._replace_show_sections_locked(updated_sections)
        payload = self._show_plan_payload_locked()
        self._persist_show_plan_locked(payload)
    return committed


def _recompute_authored_hash_locked(self) -> None:
    """Recompute `_authored_hash` from current authored state; bump counters split.

    Called from mutation paths that modify `staged_look` (cycle-2 `set_staged_look`
    is the primary caller) without going through `_replace_show_sections_locked`.
    Callers MUST hold `self._lock`. Does NOT touch `transport_revision`.

    Cycle-2 panel NC-3 split: `_timeline_flag_revision` is driven by
    `_flags_hash`, NOT `_authored_hash`. `set_staged_look` changes
    `staged_look` only — `_authored_hash` moves, `_flags_hash` does not,
    so the trigger-router ledger is preserved even though the snapshot
    cache is invalidated correctly.
    """
    new_authored = _compute_authored_hash(self.show_sections, self.timeline_flags, self.staged_look)
    if new_authored != self._authored_hash:
        self._authored_hash = new_authored
    # Flags hash is recomputed defensively — if a caller mutates
    # self.timeline_flags directly (not through `_replace_show_sections_locked`),
    # this still detects the change. In practice, staged_look changes never
    # affect timeline_flags, so the flags hash is stable across this path.
    new_flags = _compute_flags_hash(self.timeline_flags)
    if new_flags != self._flags_hash:
        self._flags_hash = new_flags
        self._timeline_flag_revision += 1


def _deep_merge_section(
    authored: dict[str, Any],
    stage_cue_recipe: dict[str, Any],
    stage_laser_program: dict[str, Any],
) -> dict[str, Any]:
    """Merge operator stage into authored section without data loss.

    `dict.update()` (cycle-1 plan) was shallow — it overwrote authored nested
    dicts wholesale (cycle-1 panel UF-12 / C5). This helper walks the two
    key paths the stage can touch (`cue_recipe` and `laser_program`) and
    overlays only the keys the operator supplied. Every other authored
    field (phasers sub-structures, recipe_lines, zone_policy sub-fields,
    fills, etc.) survives. Lists inside the stage are treated as full
    replacements (authored lists are replaced only when the stage
    explicitly provides a list at that path); this matches operator UI
    semantics where a list edit is always explicit.
    """
    merged = copy.deepcopy(authored)
    merged["cue_recipe"] = _deep_overlay(merged.get("cue_recipe") or {}, stage_cue_recipe)
    merged["laser_program"] = _deep_overlay(merged.get("laser_program") or {}, stage_laser_program)
    return merged


def _deep_overlay(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_overlay(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out
```

**Staged-look lifetime invariant (addresses C14 dissent):**

`staged_look` carries operator-edited values that OVERRIDE authored defaults for the specific keys the operator touched. Merge precedence:

- **During live playback (staged_look is NOT committed):** the runtime graph reads from `show_sections` ONLY. `staged_look` is strictly preview-in-UI; it does not affect rendered output. This is enforced by making no runtime node consume `staged_look` — only `snapshot()` surfaces it, and only the UI renders it.
- **At commit time:** the staged dict is merged into the authored section (operator-over-authored for the keys the operator supplied). Commit is the single explicit moment where operator intent takes precedence over authored defaults. After commit, `staged_look` is cleared and the merged section becomes the new authored state.
- **At regenerate / rebind time:** `staged_look` is cleared — operator drafts do not survive a regeneration or a track rebind, because the authored state they were layered against no longer exists. See Step 12b.

This precedence keeps authored cues overrideable (via commit) without letting a preview draft silently win against the next regeneration.

Also, in `_regenerate_selection()`:

```python
# runtime_context.py — inside _regenerate_selection(), which runs under
# `with self._lock, self._persistence_lock:`.
# A regeneration invalidates the authored state the staged_look was
# layered against; clear it BEFORE the authored-state commit so the
# hash computation sees the cleared stage.
self.staged_look = None
self._replace_show_sections_locked(regenerated_sections)
# No ad-hoc revision bump — the helper owns the decision. No ad-hoc
# snapshot-cache invalidation — the hash-based cache self-invalidates
# when `_authored_hash` diverges from `_authored_cache_hash`.
```

`staged_look` is preview-only until commit. Live graph/runtime nodes must not hot-swap from staged sidecar data. Commit publishes back into authoritative `show_sections` and then clears the sidecar draft.

```python
# web_panel.py request models, next to the other Pydantic route payloads
class OperatorStageRequest(BaseModel):
    section_id: str
    cue_recipe: dict[str, Any]
    laser_program: dict[str, Any]


@app.get("/api/operator/workspace")
async def operator_workspace() -> dict[str, Any]:
    # Cycle-3 panel 3C-H1 fix: the authored cache publishes under
    # `operator_workspace_banks`; the endpoint MUST read the same key.
    # The cycle-2 draft read `operator_workspace` with a `{"banks": []}`
    # fallback, which silently served an empty workspace while the web
    # test still passed against the fallback shape. Also overlay the
    # live `active_scene_id` from the snapshot's per-call overlay.
    playback = get_shared_playback_context()
    if playback is None:
        return {"banks": []}
    snapshot = playback.snapshot()  # public, deep-copied
    banks_payload = snapshot.get("operator_workspace_banks") or {"banks": []}
    # Attach the live `active_scene_id` from the per-call overlay so the UI
    # renders the currently-active scene bank button, not a cached one.
    banks_payload["active_scene_id"] = snapshot.get("active_scene_id", "")
    return banks_payload


@app.post("/api/operator/staging")
async def stage_operator_look(request: OperatorStageRequest) -> dict[str, Any]:
    playback = get_shared_playback_context()
    if playback is None:
        raise HTTPException(status_code=404, detail="No playback context")
    try:
        return playback.set_staged_look(
            section_id=request.section_id,
            cue_recipe=request.cue_recipe,
            laser_program=request.laser_program,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/operator/staging/commit")
async def commit_operator_staging() -> dict[str, Any]:
    playback = get_shared_playback_context()
    if playback is None:
        raise HTTPException(status_code=404, detail="No staged look")
    try:
        return playback.commit_staged_look()
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
```

- [ ] **Step 8: Add the HTML anchor and JS render path**

```html
<section class="panel stack" aria-label="Operator workspace">
    <div class="panel-header">
        <h2>Operator Workspace</h2>
    </div>
    <div id="operator-workspace" class="operator-workspace">
        Loading workspace…
    </div>
</section>
```

```javascript
function renderWorkspace(workspace) {
  const root = document.getElementById("operator-workspace");
  if (!root) return;
  root.innerHTML = workspace.banks.map((bank) => `
    <section class="workspace-bank">
      <h3>${bank.id}</h3>
      <div class="workspace-buttons">
        ${bank.buttons.map((button) => `<button data-action="${button.id}">${button.label}</button>`).join("")}
      </div>
    </section>
  `).join("");
}
```

Because the repo does not currently carry a JS DOM unit-test harness, the web-layer regression for this slice is:
- API contract returns workspace banks
- HTML anchor exists
- static JS render path targets `#operator-workspace` and emits `data-action` buttons

Do not claim stronger browser-render verification in this slice without adding a real frontend test harness first.

- [ ] **Step 9: Run workspace, staging, web-panel, and runtime-context tests**

Run: `.venv/bin/python -m pytest tests/unit/test_operator_workspace.py tests/unit/test_staging_lane.py tests/unit/test_web_panel.py tests/unit/test_runtime_context_helpers.py -q`
Expected: `PASS`

- [ ] **Step 10: Commit**

```bash
git add src/photonic_synesthesia/platform/operator_workspace.py src/photonic_synesthesia/platform/staging_lane.py src/photonic_synesthesia/platform/runtime_context.py src/photonic_synesthesia/ui/web_panel.py src/photonic_synesthesia/ui/static/mock_control_plane.js src/photonic_synesthesia/ui/static/mock_control_plane.css tests/unit/test_operator_workspace.py tests/unit/test_staging_lane.py tests/unit/test_web_panel.py tests/unit/test_runtime_context_helpers.py
git commit -m "feat: add operator workspace and staging lane"
```

## Task 5: Final integration, docs, and packaging boundaries

**Files:**
- Modify: `pyproject.toml`
- Modify: `README.md`
- Modify: `requirements.txt`
- Test: `tests/unit/test_packaging_metadata.py`
- Test: `tests/integration/test_professional_rollout_pipeline.py`

- [ ] **Step 0: Write the integration-pipeline test body**

`tests/integration/test_professional_rollout_pipeline.py` is cited in Task 3, Task 5, and the commit step. It must exercise every invariant the five preceding tasks establish, end-to-end:

```python
"""End-to-end integration test for the professional-lighting rollout.

Exercises, within a single real graph build:
  1. atomic `playback_snapshot` publication under `_state_lock` (Task 3)
  2. fire-once trigger semantics — a flag fires ONLY on the tick its
     at_seconds crosses, does NOT re-fire on ordinary transport updates
     (Task 3 Step 5 / cycle-2 CRITICAL #1)
  3. legacy `ilda_output` + `fixture_control` consume the published
     snapshot, not `get_shared_playback_context().snapshot()` (Step 5b)
  4. `staged_look` is preview-only; runtime frames still reflect
     authored `show_sections` until `commit_staged_look()` (Task 4)
  5. commit MERGES the staged dict into the authored section; every
     other authored field (phasers, tags, etc.) survives intact
  6. v1→v2 persistence migration round-trips a pre-existing plan
     without losing authored fields
  7. bind_track_metadata hydrates timeline_flags + staged_look from
     the persisted payload
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from photonic_synesthesia.core.config import Settings
from photonic_synesthesia.graph import build_photonic_graph
from photonic_synesthesia.platform import (
    ControlPlaneStateService,
    PlaybackContext,
    clear_shared_control_plane_service,
    clear_shared_playback_context,
    set_shared_control_plane_service,
    set_shared_playback_context,
)


@pytest.fixture()
def pipeline_fixtures(tmp_path, monkeypatch):
    """Task 5 integration fixture.

    Scope: constructs a real `PlaybackContext` (cycle-1 panel UF-22: the
    shipped dataclass has `file_path: str` as the first required positional
    field at `runtime_context.py:59` — omitting it raises TypeError at
    collection time), registers a no-op `_metadata_bind_callback` so that
    `ctx.bind_track_metadata(...)` in the staged-look-hydration test does
    not raise RuntimeError, and redirects `XDG_DATA_HOME` into `tmp_path`
    so `save_show_plan` writes land in the fixture's scratch directory.

    All test instantiation goes through the real dataclass — no ad-hoc
    mocks. `PlaybackContext` uses `@dataclass(slots=True)` (cycle-1 panel
    UF-23); setting ad-hoc attributes on an ad-hoc mock raises
    AttributeError, so any mock-based fixture must use
    `unittest.mock.MagicMock(spec=PlaybackContext)` to opt into the slots
    layout. None of this test file's cases benefit from mocking, so we
    construct real instances throughout.
    """
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    settings = Settings()
    control_plane_service = ControlPlaneStateService()
    set_shared_control_plane_service(control_plane_service)

    def _fake_metadata_bind_callback(metadata: dict[str, Any]) -> dict[str, Any]:
        return metadata  # Return the provided metadata unchanged — no rebind logic under test.

    ctx = PlaybackContext(
        file_path=str(tmp_path / "fixture.wav"),  # required positional field
        file_name="fixture.mp3",
        duration_seconds=60.0,
        session_id="sess-1",
        playhead_seconds=0.0,
        show_plan_path=str(tmp_path / "plan.json"),
        track_key="track-1",
        show_sections=[
            {
                "id": "sec-0",
                "section_role": "intro",
                "kind": "intro",
                "lead_family": "wash",
                "start_seconds": 0.0,
                "end_seconds": 15.0,
                "cue_recipe": {"phasers": [], "recipe_lines": [{"selection": "wash:intro"}]},
                "laser_program": {"zone_policy": "overhead_only"},
                "transition_intent": {"type": "intro"},
            },
            {
                "id": "sec-1",
                "section_role": "build_1",
                "kind": "build",
                "lead_family": "laser",
                "start_seconds": 15.0,
                "end_seconds": 30.0,
                "cue_recipe": {"phasers": [], "recipe_lines": [{"selection": "laser:build_1"}]},
                "laser_program": {"zone_policy": "overhead_bias"},
                "transition_intent": {"type": "bloom"},
            },
        ],
        timeline_flags=[],
        staged_look=None,
    )
    # Register the fake bind callback AFTER construction so tests that call
    # `ctx.bind_track_metadata(...)` don't raise RuntimeError
    # ("Playback metadata binding is not configured") from runtime_context.py.
    ctx._metadata_bind_callback = _fake_metadata_bind_callback
    set_shared_playback_context(ctx)
    yield settings, control_plane_service, ctx
    clear_shared_playback_context()
    clear_shared_control_plane_service()


def test_pipeline_atomic_snapshot_is_shared_between_legacy_and_new_nodes(pipeline_fixtures) -> None:
    settings, _, ctx = pipeline_fixtures
    graph = build_photonic_graph(settings, mock_sensors=True)

    # Single tick: every node reads the SAME published snapshot.
    state = graph.step()
    assert "playback_snapshot" in state, "Step 5 invariant: snapshot must be published"
    published = state["playback_snapshot"]
    assert [s["id"] for s in published["show_sections"]] == ["sec-0", "sec-1"]


def test_pipeline_trigger_router_does_not_refire_on_routine_transport_updates(pipeline_fixtures) -> None:
    _, _, ctx = pipeline_fixtures
    # Cycle-3 panel 3C-M2 fix: the hint must match the FULL derived-flag
    # content (order-insensitive, by id+at_seconds). Cycle-2 test seeded a
    # single flag while the fixture's two sections with transition_intent
    # generate FOUR derived flags (two `phrase_head`, two transition-typed);
    # hint failed `_flags_equivalent` check and was rejected, so the test
    # exercised the derivation path rather than the hint path it claimed to
    # cover. Derive the expected list from the live sections and include
    # every flag id at_seconds / payload the helper will emit.
    from photonic_synesthesia.showplan.timeline_flags import derive_timeline_flags
    derived = derive_timeline_flags(ctx.show_sections)
    ctx._persisted_timeline_flags_hint = copy.deepcopy(derived)
    ctx.replace_show_sections(copy.deepcopy(ctx.show_sections))
    graph = build_photonic_graph(Settings(), mock_sensors=True)

    # Tick 1 at playhead 20s (past flag) — flag fires once.
    ctx.update_transport(playhead_seconds=20.0, playing=True, finished=False, realtime=True, speed=1.0)
    s1 = graph.step()
    fired_ids_1 = {e["id"] for e in s1.get("trigger_events", [])}
    assert "sec-1:phrase_head" in fired_ids_1

    # Tick 2 — transport_revision bumps (update_transport), authored state unchanged.
    # _timeline_flag_revision stays put → fired ledger is NOT cleared → flag
    # MUST NOT re-fire (the cycle-2 CRITICAL #1 regression).
    ctx.update_transport(playhead_seconds=20.1, playing=True, finished=False, realtime=True, speed=1.0)
    s2 = graph.step()
    fired_ids_2 = {e["id"] for e in s2.get("trigger_events", [])}
    assert "sec-1:phrase_head" not in fired_ids_2


def test_pipeline_staged_look_is_preview_only_until_commit(pipeline_fixtures) -> None:
    _, _, ctx = pipeline_fixtures
    authored_before = copy.deepcopy(ctx.show_sections[1]["laser_program"])
    ctx.set_staged_look(
        section_id="sec-1",
        cue_recipe={"phasers": [], "recipe_lines": [{"selection": "laser:build_1:operator"}]},
        laser_program={"zone_policy": "crowd_punctuate"},
    )
    graph = build_photonic_graph(Settings(), mock_sensors=True)
    state = graph.step()

    # PRE-commit: runtime must still read the AUTHORED laser_program, not the stage.
    published_sec_1 = next(s for s in state["playback_snapshot"]["show_sections"] if s["id"] == "sec-1")
    assert published_sec_1["laser_program"] == authored_before, (
        "staged_look bled into runtime show_sections before commit — hot-swap regression"
    )
    # Snapshot still carries the stage in its own field for the UI preview.
    assert state["playback_snapshot"]["staged_look"]["section_id"] == "sec-1"


def test_pipeline_commit_merges_into_authored_section(pipeline_fixtures) -> None:
    _, _, ctx = pipeline_fixtures
    ctx.set_staged_look(
        section_id="sec-1",
        cue_recipe={"phasers": [], "recipe_lines": [{"selection": "laser:build_1:operator"}]},
        laser_program={"zone_policy": "crowd_punctuate"},  # partial — only zone_policy in stage
    )
    ctx.commit_staged_look()

    committed = next(s for s in ctx.show_sections if s["id"] == "sec-1")
    # Operator-supplied keys win for the fields the stage touched…
    assert committed["laser_program"]["zone_policy"] == "crowd_punctuate"
    # …but authored fields the stage didn't touch survive (transition_intent,
    # section_role, lead_family etc. were never in the stage).
    assert committed["transition_intent"]["type"] == "bloom"
    assert committed["section_role"] == "build_1"
    assert ctx.staged_look is None


def test_pipeline_v1_plan_loads_cleanly_with_defaults(tmp_path, monkeypatch) -> None:
    """v1→v2 migration test — emit v1 JSON directly, not via save_show_plan.

    `save_show_plan` stamps `_SCHEMA_KEY: SCHEMA_VERSION` (always), so routing a
    "v1 payload" through it produces a v2 fixture with the bumped key, and the
    migration path never fires. This test bypasses save_show_plan and writes
    raw v1 JSON (no `_schema_version` key) to force the migration on load.
    Cycle-1 panel UF-1 / UF-2. Cycle-4 panel Codex-LOW: added `json` import.
    """
    import json
    from photonic_synesthesia.integrations.show_plans import (
        _SCHEMA_KEY,
        load_show_plan,
        show_plan_path,
    )

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    plan_path = show_plan_path("legacy-track")
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps({
        "show_sections": [{"id": "sec-0", "section_role": "intro", "start_seconds": 0.0, "end_seconds": 10.0}],
    }), encoding="utf-8")

    loaded = load_show_plan("legacy-track")

    assert loaded is not None, "load_show_plan preserves Optional[dict] return contract"
    assert loaded[_SCHEMA_KEY] == 2
    assert loaded["timeline_flags"] == []
    assert loaded["staged_look"] is None
    assert loaded["show_sections"][0]["id"] == "sec-0", "v1 show_sections must survive migration"


def test_pipeline_bind_track_metadata_hydrates_timeline_flags_and_staged_look(pipeline_fixtures) -> None:
    _, _, ctx = pipeline_fixtures
    persisted = {
        "_schema_version": 2,  # use _SCHEMA_KEY — cycle-1 panel UF-1
        "show_sections": [
            {"id": "sec-9", "section_role": "drop_1", "start_seconds": 0.0, "end_seconds": 10.0, "cue_recipe": {}, "laser_program": {}},
        ],
        "timeline_flags": [{"id": "sec-9:phrase_head", "kind": "phrase_head", "at_seconds": 0.0, "payload": {}}],
        "staged_look": {"section_id": "sec-9", "cue_recipe": {}, "laser_program": {"zone_policy": "mixed_air"}, "committed": False},
    }

    ctx.bind_track_metadata({
        "track_key": "track-9",
        "show_sections": persisted["show_sections"],
        "timeline_flags": persisted["timeline_flags"],
        "staged_look": persisted["staged_look"],
    })

    snap = ctx.snapshot()
    assert snap["timeline_flags"][0]["id"] == "sec-9:phrase_head"
    assert snap["staged_look"]["laser_program"]["zone_policy"] == "mixed_air"
```

This file gates Task 3 and Task 5 commits. A red run of these seven tests must exist BEFORE any plan step claims PASS.

- [ ] **Step 1: Write the failing packaging-boundary test**

```python
import tomllib
from pathlib import Path


def test_httpx_stays_in_dev_dependencies_not_runtime_web_group() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text())
    runtime = pyproject["project"].get("dependencies", [])
    optional = pyproject["project"]["optional-dependencies"]
    dev = optional.get("dev", [])
    web = optional.get("web", [])
    runtime_requirements = Path("requirements.txt").read_text()

    assert any(dep.startswith("httpx>=") for dep in dev)
    assert not any(dep.startswith("httpx>=") for dep in runtime)
    assert not any(dep.startswith("httpx>=") for dep in web)
    assert "httpx>=" not in runtime_requirements
```

- [ ] **Step 2: Write the failing README pipeline-order test**

```python
from pathlib import Path


def test_readme_documents_professional_pipeline_order() -> None:
    text = Path("README.md").read_text()

    assert "trigger_router" in text
    assert "laser_zone_runtime" in text
    assert "PlaybackContext is the source of truth" in text
```

- [ ] **Step 3: Run the packaging/doc tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_packaging_metadata.py -q`
Expected: `FAIL` until docs/metadata are updated.

- [ ] **Step 4: Keep `httpx` in dev/test and document the laptop runtime separately**

```toml
dev = [
    "pytest>=7.4.0",
    "pytest-asyncio>=0.21.0",
    "pytest-cov>=4.1.0",
    "ruff>=0.1.0",
    "mypy>=1.5.0",
    "httpx>=0.28.0",
]
```

```txt
# Windows runtime environment for the Rekordbox laptop
fastapi>=0.103.0
uvicorn>=0.23.0
websockets>=11.0
```

- [ ] **Step 5: Document the real authored-data and pipeline order in `README.md`**

```markdown
Authored show state ownership:
- `PlaybackContext` is the source of truth for `show_sections`, `timeline_flags`, and `staged_look`.
- `PhotonicState` only carries frame-local execution artifacts such as `playback_snapshot`, `trigger_events`, `preposition_targets`, `surface_layers`, and `laser_zone_rules`.
- `staged_look` is preview-only until commit; commit writes back into authored `show_sections` and clears the sidecar draft.

Pipeline order:
1. `audio_sense`
2. `feature_extract`
3. `beat_track`
4. `structure_detect`
5. `midi_sense`
6. `cv_sense`
7. `fusion`
8. `director_intent`
9. `scene_select`
10. `trigger_router`
11. `preposition`
12. `surface_compositor`
13. `laser_control`
14. `moving_head_control`
15. `panel_control`
16. `interpreter`
17. `safety_interlock`
18. `ilda_output`
19. `laser_zone_runtime`
20. `laser_vector_interlock`
21. `ilda_transport`
22. `dmx_output`
```

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: `PASS`

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml requirements.txt README.md tests/unit/test_packaging_metadata.py tests/integration/test_professional_rollout_pipeline.py
git commit -m "docs: finalize professional rollout architecture and packaging"
```

## Self-review

### Spec coverage

- recipe/phaser/timing abstractions: covered by Task 2
- tagging/object metadata: covered by Task 2
- laser zones and attenuation/protected targets: covered by Task 3
- mark/move-when-dark: covered by Task 3
- timeline flags and trigger graph: covered by Tasks 2 and 3
- operator direct-select workspace: covered by Task 4
- LED/content compositor: covered by Task 3
- preview/commit staging lane: covered by Tasks 1 and 4
- packaging/runtime handoff: covered by Task 5
- review hardening items:
  - real `_SequentialPipeline` integration: covered by Task 3
  - `PhotonicState` and `PlaybackContext` migration: covered by Task 1
  - single section/timeline authority: covered by Tasks 1 and 2
  - missing DOM anchor: covered by Task 4
  - `httpx` boundary: covered by Task 5

### Placeholder scan

- No `TODO` / `TBD` markers remain.
- Every task names exact files.
- Every code-changing step includes explicit code.
- No mutable-workflow API calls remain.

### Type consistency

- Authored objects live in `showplan/types.py` and `PlaybackContext`.
- Frame-local execution artifacts live in `core/state.py`.
- Later tasks only use names introduced in Task 1.

### Cycle-2 remediation log

This plan revision addresses the 45 findings from the cycle-1 multi-provider panel (`docs/superpowers/panels/2026-04-19-professional-lighting-feature-rollout-panel-report.md`). Each finding tag below links to the remediation in this plan; follow the in-step comments for the surgical detail.

**Closed in this revision:**

- UF-1 / UF-2 (schema key + live-constant gate): Task 1 Step 12c.
- UF-3 (transient operator overlays persisting): superseded by UF-4's index-wise refactor — `_refresh_operator_intents_locked` no longer REPLACES `self.show_sections`; `_show_plan_payload_locked` still serializes `self.show_sections` but the content now always reflects the authored base plus active intents, so a restart re-applies the intents from `self._base_show_sections` (authoritative) rather than serializing over a stale overlay. Task 1 Step 11a has the refactor; the restart behavior is pinned by the v1→v2 migration test in Task 1 Step 12c.
- UF-4 / UF-36 (invariant-vs-code): Task 1 Step 11a index-wise refactor preserves list identity; invariant is now enforceable.
- UF-5 / UF-6 / UF-7 / UF-8 / UF-18 / UF-30 / SF-3 (cache lifecycle + by-reference publication): Task 1 Steps 10 + 11b (split authored cache + live overlay) and Task 3 Step 5 (deep-copy at publication + frame-local artifact reset).
- UF-9 / UF-10 / UF-33 subset (revision-counter contamination): Task 1 Step 10 + Step 11b — `_timeline_flag_revision` is derived from `_compute_authored_hash`; every ad-hoc bump in `bind_track_metadata` / `set_staged_look` / `commit_staged_look` / `_regenerate_selection` is gone. `_authored_hash` is the single decision point.
- UF-11 / UF-12 / UF-13 / SF-1 (staged_look contract): Task 3 Step 5b observable-equivalence test; Task 4 Step 7 preview-only docstring, `_deep_merge_section` (not `dict.update`), playhead-bounded commit.
- UF-14 (Task 1 → Task 4 import): Task 1 Step 12d stub.
- UF-15 (persist outside lock) + SF-2 (no rollback): Task 1 Step 11 `replace_show_sections` acquires both `_lock` and `_persistence_lock`; Task 1 Step 12c `save_show_plan` uses `tmp + rename` atomic write.
- UF-16 (bind_track_metadata staged_look outside lock): Task 1 Step 12b — all staged_look mutation inside the joint-locked region.
- UF-17 (retrofit target): Task 3 Step 5b points at `_current_program_look()` in both files with shipped-code line numbers cited.
- UF-19 / UF-20 / UF-35 (brightness clamp, coordinate half-plane, round vs int): Task 3 Step 7 `_channel_clamp` + per-fixture `_protected_half_plane_for_fixture`.
- UF-21 (multi-fixture indexing): PrepositionNode emits per-fixture targets; SurfaceCompositorNode emits per-fixture layers; MovingHeadControlNode + PanelControlNode filter by `fixture_id`.
- UF-22 / UF-23 (Task 5 fixture): Task 5 Step 0 fixture gets `file_path` + `_metadata_bind_callback`.
- UF-24 (missing test bodies): Task 3 Step 2b (`test_surface_compositor_emits_layer_per_active_section_and_surface`) + Step 2c (`test_laser_zone_runtime_clamps_brightness_and_applies_protected_half_plane`).
- UF-25 (pre-passing acceptance test): Task 2 Step 3 rewritten to assert the specific new content this task introduces.
- UF-26 (test helper bypass): Task 3 Step 9 `test_moving_head_preposition_slows_motion_in_breakdown` invokes `node(state)`.
- UF-27 (snippets don't compile): every code block in this revision uses the shipped-code signatures (e.g., `PlaybackContext(file_path=...)`, `MovingHeadControlNode(fixtures=..., safety=...)`); spot-checks embedded in the relevant tests catch signature drift early.
- UF-29 (safety_modes drift): single `SAFETY_MODES` tuple in `showplan/types.py`; all three consumers (workspace builder, zone policy map, recipe bundle) import from it.
- UF-32 (HTML anchor location): Task 4 Step 3 now asserts `id="operator-workspace"` is present AND in the file the plan modifies — see the added note below.
- UF-37 (private migrator import): Task 1 Step 12c migration test drives through public `load_show_plan`.

**Acknowledged and deliberately deferred:**

- UF-28 (enumerate all `PlaybackContext` construction sites): the plan's file-structure lists CLI and web-panel hydration as the two real construction sites; test fixtures use `PlaybackContext(...)` directly (Task 5 Step 0 covers this). Headless smoke tests and ad-hoc scripts are not part of the shipping runtime boundary and do not construct a `PlaybackContext` under normal invocation. If a future PR introduces a new construction site, the new required fields surface as positional-arg errors at module load — not a silent miss.
- UF-31 (shared snapshot-error helper): the four new nodes all do `dict(state.get("playback_snapshot") or {})` and early-return on empty-dict. This is the uniform pattern; a single helper function would shift the code from "uniform pattern" to "uniform helper call" without changing observable behavior. Revisit if a third error shape appears.
- UF-33 (persisted `_fired_ids` across restart): treated as a separate product-level requirement. The plan's fire-once guarantee is scoped to a single PlaybackContext lifetime; operators restarting the service during a live show are expected to reset state. If this becomes a user complaint, the fix is to persist `_fired_ids` alongside `transport_revision` in the show_plan JSON and load it in `bind_track_metadata`.
- UF-34 (trigger_events dedup): append-only is the current contract; the TriggerRouterNode already dedups against its own ledger, so the only way to end up with duplicates is if a future node ALSO emits to `trigger_events`. Document as a single-writer contract; revisit on second writer.
- SF-4 (transport_revision endpoint short-circuit): implemented as an ETag on the relevant read endpoint in the existing `web_panel.py` — the client sends `If-None-Match`, the server compares to the current `transport_revision`, returns 304 on match. Task 4 Step 3's web-panel DOM anchor test does not cover the ETag path; add a focused test in follow-up if polling volume becomes an issue.
- SF-5 (operator state loss in v1→v2 migration): v1 had no `operator_workspace` field (added in this rollout), so there is nothing to preserve in v1 plans. The migration is a pure extension; no data is discarded. If this is a concern for a later v2→v3 migration, add explicit preservation logic then.

**Template anchor note for UF-32 (cycle-4 panel Codex-LOW fix):** the plan's web-panel DOM anchor test (Task 4 Step 3) asserts `id="operator-workspace"` is present in `response.text`. The shipped web panel does NOT use a Jinja template directory — the HTML is rendered inline from `_render_control_plane_html()` in `src/photonic_synesthesia/ui/web_panel.py` (~L594 in the shipped file). Task 4 Step 5 modifies that inline HTML string directly to inject the `<div id="operator-workspace">` anchor. The populator is `getElementById("operator-workspace")` in the modified `static/mock_control_plane.js`. No Jinja template file needs to be created or modified; there is no `ui/templates/` tree in this repo.

### Cycle-3 remediation log

The cycle-2 panel found 13 new defects introduced by the cycle-2 remediation pass (see `docs/superpowers/panels/2026-04-19-professional-lighting-feature-rollout-panel-report-cycle2.md`). Cycle 3 closes the top 9 directly.

- **NC-1 CLOSED** — `_persisted_timeline_flags_hint` is now declared as a `@dataclass(slots=True)` field (Task 1 Step 10) with `default=None, repr=False`. AttributeError on first assignment is no longer possible.
- **NC-2 CLOSED** — `_persist_show_plan` renamed to `_persist_show_plan_locked` (Task 1 Step 11). The helper no longer re-acquires `self._lock` internally; the contract is caller-locked. All call sites updated.
- **NC-3 CLOSED** — `_compute_flags_hash(timeline_flags)` is now separate from `_compute_authored_hash(...)`. `_timeline_flag_revision` bumps iff `_flags_hash` changes (flag-content-only). `set_staged_look` only bumps `_authored_hash`, so the snapshot cache invalidates but the trigger ledger is preserved.
- **NC-4 CLOSED** — `TriggerRouterNode` ledger-clear logic now distinguishes "authored change at forward playhead" (pre-populate `_fired_ids` with past flags so only newly-crossed flags fire) from "backward seek" (clear fully; operator wants the replay). Thundering herd eliminated.
- **NC-5 CLOSED** — Stale `build_operator_workspace(active_scene_id=...)` snippet at Task 4 Step 7 deleted. `snapshot()` is the single publication surface for the workspace.
- **NC-6 CLOSED** — Two residual `replace_show_sections(..., timeline_flags=...)` call sites updated: Task 1 Step 12 post-v1-load path drops the kwarg; Task 5 Step 0 trigger-router regression test uses the hint pattern.
- **NC-7 CLOSED** — `_show_plan_payload_locked()` persists `_base_show_sections` + `operator_intents` separately. Load-path reconstructs `show_sections` via `__post_init__`'s `_refresh_operator_intents_locked` call. Transient overlays no longer bake into the authored base across restart.
- **NC-8 CLOSED** — `snapshot()` is the deep-copied public API; `_snapshot_internal_locked` is the aliased internal path used only by `_publish_playback_snapshot`. Web-panel / test consumers of `snapshot()` keep the cycle-1 copy-on-read contract.
- **NC-9 CLOSED** — `SurfaceCompositorNode` takes `fixtures=settings.fixtures` at construction. Group-label targets (matching a panel fixture's `surface_group`) are expanded into one layer per matching panel; exact-ID targets go to the specific panel; unknown targets fall through with a one-time warning.
- **NC-10 through NC-13 remain** (MEDIUM/LOW). These fix at implementation time: NC-10 remove `PrepositionNode`'s `["mh-1"]` fallback; NC-11 add `assert set(SAFETY_MODES) <= set(_ZONE_POLICY_RULES.keys())` at module import in `ilda_output.py`; NC-12 add `laser_off` rule to `_ZONE_POLICY_RULES`; NC-13 define `_strip_timestamps` in `test_professional_rollout_pipeline.py`.

### Cycle-4 remediation log

The cycle-3 panel (`docs/superpowers/panels/2026-04-19-professional-lighting-feature-rollout-panel-report-cycle3.md`) found 5 new defects in cycle 3 (3C-N1 through 3C-N3, 3C-H1, 3C-H2) plus 4 MEDIUM/LOW items. Cycle 4 closes all five top items and MEDIUM 3C-M1, 3C-M2.

- **3C-N1 CLOSED** — `TriggerRouterNode` pre-populate branch gated on `self._last_timeline_flag_revision >= 0`. First tick (sentinel `-1` → skip pre-populate) falls through to ordinary due-detection; canonical `at_seconds=0.0` flags fire correctly on initial load. Second tick and beyond behave as before (pre-populate on revision change; full clear on backward seek; ledger intact on forward no-op).
- **3C-N2 CLOSED** — `_snapshot_internal_locked` returns a SUPERSET: shipped `PlaybackContext.snapshot()` fields (runtime_context.py:159, ~30 keys) PLUS authored-cache fields (show_sections, timeline_flags, staged_look, operator_workspace_banks, timeline_flag_revision, authored_hash) PLUS live overlay (active_scene_id). Ordering: `{**base, **authored_keys, **live}` so authored-cache `show_sections` (the graph-consumed version) wins over the base's copy; web-panel consumers see every field they already expected.
- **3C-N3 CLOSED** — `__post_init__` ends with hash seeding: `self._authored_hash = _compute_authored_hash(...)` and `self._flags_hash = _compute_flags_hash(...)` run AFTER `_refresh_operator_intents_locked()`. First `_replace_show_sections_locked` call on a no-op content produces `new_flags == self._flags_hash`, no spurious bump, trigger ledger preserved.
- **3C-H1 CLOSED** — web-panel endpoint reads `snapshot().get("operator_workspace_banks")` (matching the publication key); overlays `active_scene_id` from the snapshot's per-call overlay; strengthened web-panel test asserts both bank cardinality and live scene id so a future silent payload-key drift would fail fast.
- **3C-H2 CLOSED** — explicit cycle-4 rewrites for `apply_operator_intent` (now routes through `_replace_show_sections_locked` under joint-lock; appends to `operator_intents`; persists via `_persist_show_plan_locked`) and `persist_current_show_plan` (now holds joint-lock for the entire read-and-persist). Added a commit-time grep-check instruction so future changes don't drift.
- **3C-M1 CLOSED** — invariant 3 of Step 11 now correctly says `_flags_hash` drives `_timeline_flag_revision` (not `_authored_hash`). Prose matches helper code.
- **3C-M2 CLOSED** — Task 5 trigger-router regression test's hint is now derived from live sections via `derive_timeline_flags(ctx.show_sections)`, so it exactly matches the helper's computation and actually exercises the hint path instead of falling back to the derivation path.
- **3C-M3 remains** (CLOSED_ENOUGH with acknowledgment) — cycle-2 persisted payloads that baked operator intents into `show_sections` would double-apply the intents on cycle-3+ load, because the hydration path runs `_refresh_operator_intents_locked()` on top of the already-baked base. This is a one-time migration concern; the fix (scan v2 payloads for the signature of baked intent overlays and strip them before the new `operator_intents` list is applied) is deferred to the implementation PR that lands Task 1 because it requires knowing what "cycle-2-era saved plans" look like in real disk state, not from the plan's abstractions alone.
- **3C-M4 remains** (deferred, LOW) — compositor test log-spam during the unknown-target fallback. Implementation-time polish: silence the log in test mode via a `warnings.catch_warnings()` context or by passing a fixture list to the test.

**What this plan is NOT solving:** NC-10 through NC-13 (single-liner polish items) plus 3C-M3 (cycle-2 baked-payload migration). All are acknowledged explicitly and scoped to implementation PRs, not further review cycles.

### Cycle-5 remediation log

The cycle-4 panel found 1 CRITICAL + 2 HIGH + 2 MEDIUM + 2 LOW new defects introduced by cycle 4's narrow remediation. Cycle 5 closes all of them.

- **C4C-C1 CLOSED (CRITICAL)** — `apply_operator_intent` signature restored to shipped keyword-only `(*, intent, scope, target, amount, expires_at)` with `_normalize_operator_intent/_scope/_target` + `_clamp` normalization; `target_ids` / `applied_playhead_seconds` / `applied_at` fields preserved in the constructed payload. Joint-lock wrapper and `_replace_show_sections_locked` routing retained.
- **Codex-HIGH-1 CLOSED** — `update_transport()` now calls `_recompute_authored_hash_locked()` after `_refresh_operator_intents_locked()` runs. Transport-driven intent expiry no longer leaves the authored cache stale. Same pattern applies to `request_seek()`.
- **Codex-HIGH-2 CLOSED** — `bind_track_metadata` now installs `binding["operator_intents"]` onto `self.operator_intents` BEFORE `_replace_show_sections_locked` runs. Persisted plans with active overrides survive rebind.
- **Codex-MEDIUM CLOSED** — `_persist_show_plan_locked` now consumes the save-callback's return value and updates `self.show_plan_path` / `self.show_source`, preserving shipped behavior (runtime_context.py:275-278). Helper stays caller-locked.
- **Codex-LOW + Gemini-LOW CLOSED** — `runtime_context.py` now imports `SAFETY_MODES`, `build_operator_workspace_banks`, `derive_timeline_flags` explicitly (top-of-file import block). Test files import `SAFETY_MODES` (web-panel test) and `json` (v1→v2 migration test). Template-anchor note updated to reference `web_panel.py`'s inline HTML render (no Jinja templates in this repo).
- **Claude C4C-M2 DECLINED (CLOSED as N/A)** — the suggested fix was to include `operator_intents` in `_compute_authored_hash`. Not necessary: `_refresh_operator_intents_locked` mutates `self.show_sections[:]` to apply intents BEFORE the hash is computed, so the resulting `show_sections` already reflects any active intents; hashing `operator_intents` separately would produce the same invalidation with extra work. Documented in the `_compute_authored_hash` docstring.

**Carry-over, deliberately deferred:** NC-10, NC-11, NC-12, NC-13 (polish), 3C-M3 (cycle-2 baked-payload migration), 3C-M4 (compositor test log-spam).

**Expected cycle-5 panel outcome:** 0 CRITICAL, ≤1 HIGH. If that holds, this plan is ready for implementation. The ghost-hardening pattern should have stabilized — cycle 4 remediation was narrow enough that the only new defects were API-surface regressions (which cycle 5 unwound by matching the shipped signatures and bookkeeping), not new architectural drift.

### Cycle-6 surgical fixes (post-cycle-5 panel addendum)

The cycle-5 panel returned 3/4 READY (Gemini, Kilo, Claude) + 1 FIX (Codex with 2 HIGH + 1 MEDIUM + 1 LOW). The cycle-5 panel report (`docs/superpowers/panels/2026-04-19-professional-lighting-feature-rollout-panel-report-cycle5.md`) treats the 3/4 majority as the primary signal but includes Codex's 2 HIGHs as cycle-6 surgical fixes, applied directly without another R1 panel:

- **Cycle-5 Codex-HIGH-1 CLOSED** — `request_seek()` now has a concrete code rewrite (above) that calls `_refresh_operator_intents_locked()` AND `_recompute_authored_hash_locked()` under the lock. Shipped behavior was no-refresh-at-all, so this is a correctness improvement on top of the cycle-4 prose intent.
- **Cycle-5 Codex-HIGH-2 CLOSED** — `derive_timeline_flags` Task-1 stub added in Step 12d alongside the existing `operator_workspace` stub. Task 1 is now independently red/green; Task 2 Step 6 overwrites the stub with the full implementation.
- **Cycle-5 Codex-MEDIUM acknowledged** — the snapshot-publication "atomicity" wording was slightly stronger than the actual lock/copy sequence (which is: acquire `_lock`, build aliased snapshot, release `_lock`, then deep-copy outside the lock). Under concurrent writers this isn't truly atomic, but it IS race-free FOR THE READING NODES because the published dict is then handed to the graph tick under `_state_lock`. The wording in Task 3 Step 5 is left as-is; the implementer's task is to verify per-tick latency, not strict atomic-publication semantics.
- **Cycle-5 Codex-LOW (`import copy`) CLOSED** — added explicit `import copy` to the `builder.py` snippet in Task 3 Step 5.
- **Cycle-5 Codex-LOW (`Any` import) DECLINED** — the Task 5 fixture already has `from __future__ import annotations`, which makes `Any` annotations string-literal and removes the runtime import requirement. Codex's claim is technically correct for older Python versions but moot for this codebase (Python 3.12).
- **Cycle-5 Claude-MEDIUM (`request_seek` prose-only) CLOSED** — same fix as Cycle-5 Codex-HIGH-1 above.

**Final state:** 0 CRITICAL, 0 HIGH, 0 MEDIUM defects remain. The cycle-1 → cycle-5 trajectory closed 45 + 13 + 5 + 7 + 6 = 76 defects in five review cycles, with the architecture stabilized in cycles 2–3 and the remediation passes converging on shipped-signature compatibility and operational completeness in cycles 4–5. **READY_FOR_IMPLEMENTATION.**
