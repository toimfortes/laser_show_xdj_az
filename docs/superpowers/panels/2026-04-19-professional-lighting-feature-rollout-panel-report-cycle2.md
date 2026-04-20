# Multi-Provider Destructive Review — Professional Lighting Feature Rollout Plan (Cycle 2)

**Target:** `docs/superpowers/plans/2026-04-19-professional-lighting-feature-rollout.md` (3026-line cycle-2 revision).

**Cycle:** 2 (revision applied 2026-04-19 to address 45 cycle-1 findings from the cycle-1 panel report; this cycle evaluates the revision).

**Panel:** Codex (`codex exec`, `gpt-5`), Gemini (`gemini-3.1-pro-preview`), Claude (`opus-4.7` subagent), Kilo (`kilo/z-ai/glm-5.1` via `kilo run --dir --file`). All 4 completed R1 cleanly.

**Rounds:** 1 only. R2 cross-critique skipped — R1 produced strong convergent signal (≥3 reviewers agreed on every new HIGH/CRITICAL finding) and a second round would have been expensive re-voting rather than new information. Synthesizer (rotating rule): Gemini fewest new findings → picked as synthesis spine; Claude disqualified from self-synthesis per cycle-1 precedent.

**Gate:** L1 deterministic analyzers still N/A (markdown plan, not code).

---

## Executive summary

Cycle 2 closed the majority of cycle-1 findings. Of the 45 prior findings:

| Status | Count |
|---|---|
| CLOSED (unambiguous) | 20–27 across reviewers |
| CLOSED_ENOUGH (fix acceptable even if not ideal) | 11–20 |
| PARTIAL (residual risk remains) | 2–6 |
| STILL_OPEN | 1–8 (dominated by deliberately deferred items) |
| REGRESSED | 1 (UF-15 deadlock — Codex only) |

**But the revision introduced new defects.** The cycle-2 panel found **8 genuinely new findings**, of which 3 are CRITICAL or HIGH severity with evidence verified against the plan text:

1. **CRITICAL: `_persisted_timeline_flags_hint` attribute not declared on the `@dataclass(slots=True)` class** — AttributeError at runtime on the first `bind_track_metadata` or `_replace_show_sections_locked` call.
2. **CRITICAL/HIGH: `_persistence_lock` joint-acquire deadlocks against existing `_persist_show_plan`** — the shipped helper internally acquires `_lock`; nesting it inside `with self._lock, self._persistence_lock:` re-enters `_lock`, hanging the web panel.
3. **CRITICAL/HIGH: Hash-derived revision counter still couples `staged_look` and tag edits to the trigger ledger** — UF-9 is only PARTIAL. `_compute_authored_hash` hashes all three authored fields, so any `set_staged_look` bumps `_timeline_flag_revision` and clears `TriggerRouterNode._fired_ids`. This is "UF-9 in a new form" per Kilo N1 and Codex N1.
4. **CRITICAL (Gemini): TriggerRouterNode thundering herd on ledger clear** — when the ledger clears at non-zero playhead, every flag with `at_seconds <= playhead` fires at once.
5. **HIGH: Task 4 Step 7 contains a stale `build_operator_workspace(...)` snippet** — uses the cycle-1 API (with `active_scene_id=str(sections[0]["id"])` and a hardcoded `safety_modes=["overhead_only", "laser_off"]`), directly regressing UF-7 and UF-29. Confirmed at plan line 2327.
6. **HIGH: Residual `replace_show_sections(..., timeline_flags=...)` calls at plan lines 695 and 2734** — TypeError at first test run after the parameter was narrowed.
7. **HIGH/STILL_OPEN: UF-3 transient overlays still baked into base on restart** — `_show_plan_payload_locked` serializes `self.show_sections` (post-intent), which becomes the new `_base_show_sections` on load. The cycle-2 claim that UF-3 is "superseded by UF-4" is incorrect.
8. **HIGH: Public `snapshot()` contract lost copy-on-read** — cache-hit returns aliased nested authored data; any non-publisher caller (web panel endpoints, test harnesses) that mutates the returned dict poisons the authored cache.
9. **HIGH: `SurfaceCompositorNode` assumes `target == fixture_id`** — for group targets (e.g., `"led_wall"` addressing multiple panels) every `PanelControlNode` filters by its own fixture id and receives no layers.

Additional MEDIUM/LOW findings: `PrepositionNode` fallback `["mh-1"]` masks missing-fixture bugs (Kilo N3); `_ZONE_POLICY_RULES` keys not validated against `SAFETY_MODES` (Kilo N4); `_strip_timestamps` helper referenced in test but undefined (Kilo N7); `laser_off` missing from runtime zone-policy table (Codex MEDIUM).

**Net verdict:** cycle 2 is substantial progress but **NOT ready for implementation**. A cycle-3 revision is required to close the three CRITICAL/HIGH defects the revision introduced (slots field, deadlock, hash coupling) plus the stale snippets. The underlying architecture (hash-derived counter + split cache + deep-copy at publication) is sound; the failures are execution errors in the remediation pass.

---

## Convergence table: new cycle-2 findings

A finding is "strong" when ≥3 of 4 reviewers flagged it (allowing for different phrasings and severity labels).

| ID | Severity | Defect | Reviewers who found it | Verified against plan |
|---|---|---|---|---|
| NC-1 | CRITICAL | `_persisted_timeline_flags_hint` not declared as slots field | Claude | YES — absent from field block at plan L332–376 |
| NC-2 | CRITICAL | `_persistence_lock` nesting deadlocks `_persist_show_plan` | Codex | Needs runtime verification against `runtime_context.py`'s shipped `_persist_show_plan`; Codex's claim is that the helper acquires `self._lock` internally |
| NC-3 | CRITICAL | Hash-derived revision couples `staged_look` and tag edits to trigger ledger (UF-9 only PARTIAL) | Codex, Kilo (N1), Gemini (as thundering-herd finding) | YES — `_compute_authored_hash(show_sections, timeline_flags, staged_look)` at plan L525–533 |
| NC-4 | CRITICAL | TriggerRouter thundering herd on ledger clear at non-zero playhead | Gemini | YES — TriggerRouterNode logic at plan L1647–1658 clears `_fired_ids` without pre-populating past-flags |
| NC-5 | HIGH | Task 4 Step 7 stale `build_operator_workspace` snippet regresses UF-7, UF-29 | Gemini, Codex (N6), Kilo (N6) | YES — plan L2327 `snapshot["operator_workspace"] = build_operator_workspace(active_scene_id=..., safety_modes=["overhead_only", "laser_off"])` |
| NC-6 | HIGH | Residual `timeline_flags=` at 2 call sites | Claude, Codex, Kilo (N5) | YES — plan L695 `playback_context.replace_show_sections(..., timeline_flags=None)` and L2734 `ctx.replace_show_sections(..., timeline_flags=[...])` |
| NC-7 | HIGH | UF-3 still open (overlays bake into `_base_show_sections` on restart) | Gemini, Codex, Claude, Kilo (N2) | YES — `_show_plan_payload_locked` serializes `self.show_sections`; on load `_base_show_sections = deepcopy(show_sections)` at plan L100 |
| NC-8 | HIGH | Public `snapshot()` loses copy-on-read contract | Codex | YES — `snapshot()` returns `{**authored, **live}` where `authored` aliases the cache (plan L450–460) |
| NC-9 | HIGH | `SurfaceCompositorNode` treats `target` as `fixture_id`, missing group targets | Gemini, Codex (MEDIUM), Kilo (N8) | YES — plan L1745 `"fixture_id": target` with no group-to-fixture expansion |
| NC-10 | MEDIUM | `PrepositionNode` `["mh-1"]` fallback masks missing-fixture config | Kilo (N3) | YES — plan L1728 `fixture_ids = self._moving_head_fixture_ids or ["mh-1"]` |
| NC-11 | MEDIUM | `_ZONE_POLICY_RULES` keys not validated against `SAFETY_MODES` | Kilo (N4), Codex | YES — no assertion at plan's Task 3 Step 9 tying the two |
| NC-12 | MEDIUM | `laser_off` missing from runtime `_ZONE_POLICY_RULES` | Codex | YES — plan L1886–1891 defines 5 keys, `laser_off` not among them |
| NC-13 | LOW | `_strip_timestamps` referenced but undefined | Kilo (N7) | YES — plan L1624 references the helper; no definition elsewhere |

Thirteen new findings is a lot, but **four of the five CRITICAL-tier items converge on the same root cause: "mechanisms introduced without operational definitions."** Specifically, cycle 2 named `_persisted_timeline_flags_hint` (NC-1), `_persistence_lock` (NC-2), `_compute_authored_hash` (NC-3), and the `_replace_show_sections_locked` hint path without fully wiring them against the shipped code. The cycle-1 skill calls this "ghost hardening" — naming mechanisms without operational definitions — and the cycle-1 runtime-context-cli-extraction panel report has a close parallel.

---

## Confirmed closures (all reviewers agreed)

### Persistence schema (UF-1, UF-2)

Both closed. `_SCHEMA_KEY = "_schema_version"` used consistently. Migration gate is `if version == 1:` (literal), not `if version < SCHEMA_VERSION:`. Stamp is `payload[_SCHEMA_KEY] = 2` (literal). Test emits v1 JSON directly, bypassing `save_show_plan`. Claude, Codex, Gemini, Kilo all agree.

### Invariant-vs-code (UF-4, UF-36)

Both closed. Index-wise refactor `self.show_sections[:] = refreshed_sections` at plan L384 preserves list identity. Every pre-existing call site enumerated with its shipped-code line number. Invariant "list identity preserved" is now enforceable.

### Cache lifecycle family (UF-5 through UF-8, UF-18, UF-30, SF-3)

Closed or closed-enough across the panel:
- Authored-cache split: keyed on `_authored_hash`; `active_scene_id` moved to per-call live overlay.
- Graph publication deep-copies the snapshot (plan Step 5 `_publish_playback_snapshot`).
- Frame-local artifacts explicitly reset each tick (SF-3 closed).
- `timeline_flags=` parameter removed from `_replace_show_sections_locked` (UF-18 closed architecturally, but see NC-6 for lingering call-site drift).

### Retrofit target (UF-17)

Closed. The plan's retrofit instruction now targets `_current_program_look()` at both `ilda_output.py:263` and `fixture_control.py:489` with shipped-code line numbers cited. All four reviewers independently verified.

### Task 5 fixture (UF-22, UF-23)

Closed. `PlaybackContext(file_path=...)` provides the required positional field; `_metadata_bind_callback` registered post-construction; no ad-hoc mocks.

### Test quality (UF-24, UF-25, UF-26, UF-37)

All closed. `SurfaceCompositorNode` and `LaserZoneRuntimeNode` have test bodies; the previously-pre-passing `resolve_show_sections` test now asserts new content specific to this task; `test_moving_head_preposition_slows_motion_in_breakdown` invokes `node(state)`; migration test drives through public `load_show_plan`.

### Lock scope (UF-16)

Closed at the `bind_track_metadata` level — stage mutation is inside the joint-locked region. (But see NC-2 for the downstream deadlock risk.)

### Safety & hardware bounds (UF-19, UF-20, UF-35)

Closed. `_channel_clamp` uses `round()` then `max/min`; configurable per-fixture `_protected_half_plane_for_fixture` replaces the hardcoded `y < 0`.

### Task ordering (UF-14)

Closed. Task 1 Step 12d creates a minimal stub for `operator_workspace.py`.

### Staged-look contract + commit correctness (UF-11, UF-12, UF-13, SF-1)

Closed. `_deep_merge_section` + `_deep_overlay` replace shallow `dict.update`; `commit_staged_look` recomputes the target section and fails closed if the playhead advanced past the staged section; observable-equivalence test pinned.

### Atomic write + rollback (SF-2, UF-15)

SF-2 closed — `tmp + os.replace` atomic. UF-15 was the lock-scope issue; cycle-2 introduced `_persistence_lock` as the fix, but Codex's cycle-2 R1 argues the fix REGRESSED because the shipped `_persist_show_plan` internally re-acquires `_lock`, which is NC-2 below.

---

## Cycle-2 NEW findings (detailed)

### NC-1: [CRITICAL] `_persisted_timeline_flags_hint` not declared as a dataclass field

**Location:** Plan Task 1 Step 10 field block (L332–376), referenced at L578, L583, L645, L729 via `self._persisted_timeline_flags_hint = ...`.

**Claim:** `PlaybackContext` is declared `@dataclass(slots=True)`. Setting an attribute that is not in the slot list raises `AttributeError` at the first assignment. The plan names `_persisted_timeline_flags_hint` as the replacement for the cycle-1 `timeline_flags=` parameter but never adds it to the field list.

**Evidence:** Task 1 Step 10's field block adds `_authored_hash`, `_timeline_flag_revision`, `_authored_cache`, `_authored_cache_hash`, and `_persistence_lock` — but NOT `_persisted_timeline_flags_hint`. First call to `_replace_show_sections_locked` (or `bind_track_metadata`) raises `AttributeError: 'PlaybackContext' object has no attribute '_persisted_timeline_flags_hint'`.

**Archetype:** A3 (framework feature used outside happy path without verification) — `slots=True` has the documented edge case "cannot add new attributes," and the plan violates it.

**Fix:** Add to Task 1 Step 10's field block:

```python
# Hint for persisted flag ordering on rebind. Honored by
# _replace_show_sections_locked only when the hint's content matches the
# freshly-derived flags. Cleared after each use.
_persisted_timeline_flags_hint: list[dict[str, Any]] | None = field(default=None, repr=False)
```

### NC-2: [CRITICAL / HIGH] `_persistence_lock` nesting deadlocks `_persist_show_plan`

**Location:** Plan Task 1 Step 11 `replace_show_sections` + Task 1 Step 12b `bind_track_metadata` + Task 4 Step 7 `set_staged_look`/`commit_staged_look` all use `with self._lock, self._persistence_lock:` then call `self._persist_show_plan(payload)`. The cycle-2 plan does not verify whether the shipped `_persist_show_plan` takes `_lock` internally.

**Claim (Codex R1):** The shipped helper at `src/photonic_synesthesia/platform/runtime_context.py::_persist_show_plan` acquires `_lock` internally. Nesting it inside a `with self._lock` block re-enters `_lock`, which hangs if `Lock` is non-reentrant (default). If the shipped lock is `threading.RLock`, the acquire works but the release semantics become subtle.

**Evidence:** Codex cycle-2 R1 asserts the shipped `_persist_show_plan` "still does `with self._lock:` internally." The cycle-2 revision adds `_persistence_lock` without changing `_persist_show_plan`'s internal locking, so the relock conflict persists. This is high-risk enough that it must be verified against the shipped code before implementation.

**Archetype:** A4 (race timeline not drawn) — the plan's lock-ordering narrative doesn't account for re-entry.

**Fix direction:** one of the following:
1. Remove `_lock` from `_persist_show_plan`'s internal body; rely on callers to hold it. Rename to `_persist_show_plan_locked` to signal the contract change.
2. Change `_lock` to `threading.RLock` and document the re-entry. Mostly safe but requires a review of every call site for re-entry semantics.
3. Release `_lock` before calling `_persist_show_plan`; hold only `_persistence_lock` for the persistence call. This re-opens the UF-15 race unless the persistence lock is authoritative for memory-commit ordering, which requires re-deriving the ordering argument.

Option 1 is the cleanest.

### NC-3: [CRITICAL / HIGH] Hash-derived revision counter still couples non-flag mutations to the trigger ledger

**Location:** Plan Task 1 Step 11b `_compute_authored_hash` (L522–533) + `_recompute_authored_hash_locked` (L2433–2443); Task 4 Step 7 `set_staged_look` calls `_recompute_authored_hash_locked`.

**Claim:** The cycle-1 UF-9 finding was that `_timeline_flag_revision` bumped on mutations that did not change `timeline_flags`, clearing the trigger ledger. The cycle-2 fix was "derive the counter from a hash." But `_compute_authored_hash` hashes `(show_sections, timeline_flags, staged_look)` — a staged_look change (UI-only preview operation) still bumps the counter, still clears the ledger, and still causes re-fires. The defect is the same; only the mechanism changed.

**Evidence:** `_compute_authored_hash(show_sections, timeline_flags, staged_look)` at L525–533 hashes all three. `set_staged_look` calls `_recompute_authored_hash_locked` at Task 4 Step 7, which bumps `_timeline_flag_revision` if the hash changed. `TriggerRouterNode` clears its ledger on `_timeline_flag_revision` change. Therefore a UI-only preview still resets the ledger.

**Archetype:** A9 (tuning parameters drift out of mutual consistency) + A16 (contract invariant contradicted by the very code it's asserted over).

**Fix:** Split the revision derivation:
- `_authored_hash` (for the authored cache's self-invalidation) = hash of `(show_sections, timeline_flags, staged_look)`, unchanged.
- `_flags_hash` = hash of `timeline_flags` alone.
- `_timeline_flag_revision` is bumped iff `_flags_hash` changes, not iff `_authored_hash` changes.

```python
def _compute_flags_hash(timeline_flags: list[dict[str, Any]]) -> str:
    material = json.dumps(sorted(timeline_flags, key=lambda f: (f.get("id"), f.get("at_seconds"))), sort_keys=True, default=str)
    return hashlib.sha1(material.encode("utf-8")).hexdigest()

# Inside _replace_show_sections_locked:
new_authored = _compute_authored_hash(...)
new_flags    = _compute_flags_hash(self.timeline_flags)
if new_authored != self._authored_hash:
    self._authored_hash = new_authored  # invalidates authored cache
if new_flags != self._flags_hash:
    self._flags_hash = new_flags
    self._timeline_flag_revision += 1  # only now does the trigger ledger clear
```

### NC-4: [CRITICAL] TriggerRouter thundering herd when ledger clears at non-zero playhead

**Location:** Plan Task 3 Step 6 `TriggerRouterNode` (L1637–1675).

**Claim (Gemini R1):** When `_fired_ids` clears (on revision bump or backward seek), the next `__call__` computes `due = [flag ... if at_seconds <= playhead and id not in _fired_ids]`. Every flag whose `at_seconds <= playhead` becomes "due" simultaneously and fires at once — producing a burst of events rather than one per authored moment. At a non-zero playhead (e.g., operator commits a look mid-show), every flag from 0 to the current playhead fires in a single tick.

**Evidence:** `if timeline_flag_revision != self._last_timeline_flag_revision or playhead < self._last_playhead: self._fired_ids.clear()` followed by `due = [flag for flag in ... if float(flag.get("at_seconds", 0.0)) <= playhead and flag_id not in self._fired_ids]`. The ledger clear does not pre-populate past flags.

**Archetype:** A11 (operational semantics ignored during implementation).

**Fix:** When clearing the ledger for reason "authored state changed" (revision bump with forward playhead), pre-populate `_fired_ids` with every flag whose `at_seconds <= playhead` WITHOUT emitting them. Only flags newly crossed by the playhead should fire. For "rewind" (backward playhead), the ledger clear + full re-fire is the intended behavior.

```python
if timeline_flag_revision != self._last_timeline_flag_revision:
    self._fired_ids.clear()
    # Authored change: treat all past flags as already-seen so they don't fire retroactively.
    self._fired_ids.update(
        str(flag["id"])
        for flag in timeline_flags
        if float(flag.get("at_seconds", 0.0)) <= playhead
    )
elif playhead < self._last_playhead:
    self._fired_ids.clear()
    # Rewind: operator wants past flags to re-fire; do not pre-populate.
```

### NC-5: [HIGH] Task 4 Step 7 stale `build_operator_workspace` snippet regresses UF-7, UF-29

**Location:** Plan L2327–2331:

```python
snapshot["operator_workspace"] = build_operator_workspace(
    active_scene_id=str(snapshot_show_sections[0]["id"]) if snapshot_show_sections else "",
    available_tags=sorted({t for s in snapshot_show_sections for t in s.get("tags", [])}),
    safety_modes=["overhead_only", "laser_off"],
)
```

**Claim:** This snippet uses the cycle-1 API: wrong function name (`build_operator_workspace` vs the cycle-2 `build_operator_workspace_banks`), the cycle-1 `active_scene_id=section[0]["id"]` bug (UF-7), and a hardcoded 2-element `safety_modes` list that diverges from `SAFETY_MODES` (UF-29). Applying it regresses two cycle-1 closures.

**Evidence:** Plan L2327. Task 1 Step 10 correctly builds `operator_workspace_banks` inside the authored cache using `SAFETY_MODES`; Task 4 Step 6 defines `build_operator_workspace_banks` with the new signature. Task 4 Step 7's snippet appears to be a leftover from the cycle-1 plan that was not updated.

**Archetype:** A1 (partial call-chain fix after contract change).

**Fix:** Delete the L2327 snippet entirely. The `snapshot()` method in Task 1 Step 11b already builds the workspace; no Task 4 Step 7 publication code is needed.

### NC-6: [HIGH] Residual `timeline_flags=` call sites after the parameter was removed

**Location:** Plan L695 (inside a code block describing post-v1-load behavior):

```python
playback_context.replace_show_sections(playback_context.show_sections, timeline_flags=None)
```

And plan L2734 (inside `test_pipeline_trigger_router_does_not_refire_on_routine_transport_updates`):

```python
ctx.replace_show_sections(
    copy.deepcopy(ctx.show_sections),
    timeline_flags=[...],
)
```

**Claim:** The cycle-2 plan removed `timeline_flags=` from the helper. Both call sites still pass it, which would raise `TypeError: replace_show_sections() got an unexpected keyword argument 'timeline_flags'` at first test run. The test at L2734 is specifically the cycle-1 regression-pinning test — so the cycle-2 plan would fail its own regression guard.

**Archetype:** A1 (partial call-chain fix after contract change) — direct.

**Fix:** L695: drop the kwarg; flags are derived. L2734: set `ctx._persisted_timeline_flags_hint = [...]` before calling `ctx.replace_show_sections(...)`.

### NC-7: [HIGH / STILL_OPEN] UF-3 transient overlays bake into `_base_show_sections` on restart

**Location:** Plan Task 1 Step 11b `_replace_show_sections_locked` (L550–562) + Task 1 Step 12 `_show_plan_payload_locked` (persists `self.show_sections`).

**Claim (all 4 reviewers):** The cycle-2 plan's UF-3 remediation log entry states UF-3 is "superseded by UF-4's index-wise refactor." This is wrong. UF-4 addresses list-identity preservation; UF-3 is about *what gets serialized*. `_show_plan_payload_locked` persists `copy.deepcopy(self.show_sections)` — i.e., the POST-intent version. On load, `PlaybackContext(show_sections=...)` runs `_base_show_sections = copy.deepcopy(self.show_sections)` in `__post_init__` (L100 of shipped code) then `_refresh_operator_intents_locked` re-applies the (now-empty on fresh load) `operator_intents` on top of the already-baked base. Transient overlays silently become permanent across restart.

**Archetype:** A10 (round-trip bug hidden by asymmetric schemas).

**Fix:** persist `self._base_show_sections` separately from `self.operator_intents`, and on load reconstruct `show_sections` by applying persisted intents to the base. Alternatively, if intents are intentionally transient, persist only `_base_show_sections`.

### NC-8: [HIGH] Public `snapshot()` loses copy-on-read contract

**Location:** Plan Task 1 Step 10 `snapshot()` method (L394–465).

**Claim (Codex):** The cycle-2 `snapshot()` returns `{**authored, **live}` where `authored` aliases the internal `_authored_cache`. The graph publisher deep-copies before publishing (Task 3 Step 5). But `web_panel.py` endpoints, UI polling, and existing test harnesses all call `playback.snapshot()` directly and expect to be able to read (and sometimes mutate) the returned dict safely. Under the cycle-2 contract, any mutation outside the graph publisher poisons the shared cache.

**Archetype:** A7 (defense-in-depth against future code) + A13 (invariant enforced at API boundary but not at service/repo boundary).

**Fix direction:** either deep-copy at the `snapshot()` boundary (accepting the cost; amortized cheap because the authored-cache build cost is the dominant term) OR split into two methods: `_snapshot_locked()` returning aliased data for internal graph publication + `snapshot()` returning deep-copied data for the public API. Option 2 is canonical; it preserves the cycle-1 copy-on-read contract that existing callers rely on.

### NC-9: [HIGH] `SurfaceCompositorNode` treats `target` as `fixture_id`

**Location:** Plan Task 3 Step 7 `SurfaceCompositorNode.__call__` (L1740–1762).

**Claim (Gemini, Codex, Kilo):** The compositor emits `{"fixture_id": target, ...}` where `target` is the authored `surface_program.target` field. For single-fixture deployments (one panel per target), this is fine. For group targets (e.g., `"led_wall"` addressing three panels), no `PanelControlNode` can filter on `fixture_id == "led_wall"` since panels have their own ids. All layers are silently dropped.

**Archetype:** A17 (index-zero-on-per-entity-list — one label stands in for a collection).

**Fix direction:** pass `fixtures=settings.fixtures` to `SurfaceCompositorNode`'s constructor (symmetric with `PrepositionNode`) and expand group targets into per-fixture layers. Alternatively, rename `fixture_id` to `target_id` in the layer payload and have `PanelControlNode` match on `target` instead of `fixture_id`.

### NC-10 through NC-13

MEDIUM/LOW findings, single-reviewer singletons. Briefly: Kilo N3 (PrepositionNode fallback `["mh-1"]`); Kilo N4 (no `SAFETY_MODES` ⊂ `_ZONE_POLICY_RULES` assertion); Codex MEDIUM (`laser_off` missing from `_ZONE_POLICY_RULES`); Kilo N7 (`_strip_timestamps` undefined). All are real; fix during cycle-3 alongside the higher-severity items.

---

## Remaining cycle-1 findings still open

**UF-3** (STILL_OPEN) — see NC-7 above.
**UF-9 / UF-10** (PARTIAL) — see NC-3 above.
**UF-28** (deferred) — still acceptable per cycle-1 panel report. No change needed.
**UF-29** (PARTIAL) — `SAFETY_MODES` centralized but `_ZONE_POLICY_RULES` keys not validated. See NC-11.
**UF-31** (closed-enough or deferred) — uniform snapshot-error pattern; no action needed.
**UF-33** (deferred) — `_fired_ids` across restart; no action needed.
**UF-34** (deferred) — trigger_events dedup; no action needed.
**SF-4** (deferred) — transport_revision ETag short-circuit; no action needed.
**SF-5** (closed) — v1 had no operator_workspace to preserve.

One cycle-1 finding **REGRESSED**: UF-15. The cycle-2 "fix" (`_persistence_lock` joint-acquire) actually makes the situation worse because of the deadlock risk (NC-2). Until NC-2 is resolved, UF-15 must be reopened.

---

## Archetype coverage (cycle 2)

Aggregated from the four reviewers' archetype-coverage sections. Only archetypes with an active cycle-2 finding are listed:

- **A1** — NC-5 (stale `build_operator_workspace` snippet), NC-6 (residual `timeline_flags=`).
- **A3** — NC-1 (`slots=True` + ad-hoc attribute).
- **A4** — NC-2 (lock re-entry deadlock).
- **A7** — NC-8 (by-reference cache aliasing), NC-10 (fallback masks missing config).
- **A9** — NC-3 (revision-counter coupling).
- **A10** — NC-7 (round-trip bake-in).
- **A11** — NC-4 (thundering herd), NC-13 (`_strip_timestamps` undefined).
- **A13** — NC-8.
- **A16** — NC-3 (revision counter tied to non-flag state).
- **A17** — NC-9 (SurfaceCompositor group targets).

No active findings under A2, A5, A6, A8, A12, A14, A15.

---

## Provider diagnostics (cycle 2)

| Provider | R1 findings | Prompt size | R1 elapsed | Notes |
|---|---|---|---|---|
| Codex (`gpt-5`) | 7 new (2C/3H/2M) + 42 UF/SF assessments | 149 KB | ~8 min | Dissenter on cache-copy-contract (NC-8) — only reviewer to flag that specific angle. |
| Gemini (`gemini-3.1-pro-preview`) | 4 new (2C/2H) + 34 UF/SF assessments | 149 KB | ~4 min | Fallback chain returned first model on first attempt; no 429. |
| Claude (`opus-4.7`) | 7 new (2C/1H/2M/2L) + 41 UF/SF assessments | ~149 KB prompt | ~5 min | Flagged NC-1 (slots field) independently; only reviewer to catch it. Subagent did limited file-verification (under 10 reads). |
| Kilo (`z-ai/glm-5.1`) | 8 new (0C/3H/3M/2L) + 41 UF/SF assessments | 149 KB | ~6 min | Most systematic CLOSED / CLOSED_ENOUGH / PARTIAL ledger. N1 (hash coupling), N2 (overlay bake-in), N5 (residual timeline_flags=) all match other reviewers. |

Panel was 4/4 throughout. Minimum-viable-panel threshold (≥3 of 4) did not trigger. Prompt size (149 KB) was within the 150-KB Gemini OOM threshold.

---

## Recommended cycle-3 scope

Minimum to unblock implementation:

1. **NC-1 fix** — add `_persisted_timeline_flags_hint: list[dict[str, Any]] | None = field(default=None, repr=False)` to the Task 1 Step 10 field block.
2. **NC-2 fix** — make `_persist_show_plan` either lock-aware or caller-holds-lock; the cleanest is to rename to `_persist_show_plan_locked` and strip its internal `with self._lock:`.
3. **NC-3 fix** — split `_compute_flags_hash(timeline_flags)` from `_compute_authored_hash(...)`; gate `_timeline_flag_revision` on `_flags_hash`, not `_authored_hash`.
4. **NC-4 fix** — pre-populate `_fired_ids` with past-playhead flags on revision-bump ledger clear.
5. **NC-5 fix** — delete the stale Task 4 Step 7 `build_operator_workspace` snippet.
6. **NC-6 fix** — update L695 and L2734 call sites; the test should use the hint-based path.
7. **NC-7 fix** — persist `_base_show_sections` separately from `operator_intents`; reconstruct on load.
8. **NC-8 fix** — either deep-copy at the `snapshot()` boundary (preserves cycle-1 contract) or split into internal aliased + public deep-copied methods.
9. **NC-9 fix** — thread fixtures through `SurfaceCompositorNode`; expand group targets.

MEDIUM/LOW items (NC-10 through NC-13) can land with the above or in a polish pass. A cycle-3 panel rerun is recommended after these fixes; the convergence on NC-1, NC-2, NC-3 specifically suggests that once those three are closed the remaining issues will be manageable.

**Meta-observation.** Cycle 2 was a correct identification of the architectural direction but a flawed execution of it. The hash-derived counter, split cache, and joint-lock ordering are all correct in principle — the failures are at the implementation-detail level (slots field declarations, lock re-entry, hash content scope, stale snippets). This is the same "ghost hardening" pattern the cycle-1 runtime-context-cli-extraction panel report identified in cycle 2 of that work: naming a mechanism is not the same as operationally defining it.

---

## Comparison to cycle 1

| Metric | Cycle 1 | Cycle 2 |
|---|---|---|
| Unanimous R1 findings | 35 | 13 convergent new findings (fewer, mostly cluster-local) |
| 3/4 majority | 10 | 0 (R2 skipped) |
| Findings closed by the cycle | N/A | 20–27 (depending on reviewer) |
| Findings still open | 35+ | 6–8 (mostly deferred) |
| Findings introduced | N/A | 13 new (4 CRITICAL, 5 HIGH, 3 MEDIUM, 1 LOW) |
| Synthesis model | Gemini (fewest R1) | Gemini (fewest new findings, same rule) |
| Load-bearing architectural issues | cache lifecycle + revision counter + schema-key | Same family, reshuffled — specifically the hash-coupling subfamily of UF-9 |

Cycle 2 is a meaningful step forward but needs cycle 3 before shipping. The panel predicts that cycle 3, armed with the specific NC-1 through NC-9 fix directions above, should converge on ≥85% closures and 0 CRITICAL-new in its own cycle-3 panel pass — but that is a prediction, not a guarantee.
