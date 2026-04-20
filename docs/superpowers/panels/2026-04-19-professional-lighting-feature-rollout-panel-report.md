# Multi-Provider Destructive Review — Professional Lighting Feature Rollout Plan

**Target:** `docs/superpowers/plans/2026-04-19-professional-lighting-feature-rollout.md` (2207 lines, pre-code plan-phase review).

**Cycle:** 1 (run 2026-04-19, from scratch after session reboot).

**Panel:** Codex (`codex exec`), Gemini (`gemini-3.1-pro-preview` via fallback wrapper), Claude (`general-purpose` subagent), Kilo (`kilo run --dir --file`, `kilo/z-ai/glm-5.1`).

**Round-1 findings:** Gemini 6, Codex 7, Kilo 14, Claude 19 → reviewer ordering A/B/C/D for anonymized cross-critique.

**Synthesizer:** rotating rule picks Gemini (fewest R1 findings). Synthesis authored by the orchestrator using Gemini's R2 tally as the consensus spine, per the `multi-provider-review` skill. Claude (R1 most) is explicitly disqualified from self-synthesis.

**Rounds:** 2 (R1 independent + R2 anonymized cross-critique).

**Gate:** L1 deterministic analyzers (`super_audit.py`, `code_auditor`) are N/A — target is a markdown plan, not code. No deterministic findings to dismiss.

---

## Consensus summary

| Consensus | Count | Note |
|---|---|---|
| 4/4 unanimous | 35 | Auto-include, no dissent. |
| 3/4 majority | 10 | All 10 dissents came from Codex except one; Claude R2 dissented on C13, Kilo R2 dissented on C11. |
| 2/4 split | 0 | — |
| 1/4 singleton | 5 (NEW in R2) | Three deeply verified, two held for later. |

**Ten majority dissents cluster on a single reviewer pattern:** Codex preferred narrower findings (policy calls, documentation gaps) over broader "defense-in-depth" framings. This is a legitimate editorial disagreement, not a pattern of Codex blindness. Each 3/4 finding is included with the dissenting reviewer's counter-claim noted verbatim.

**Defining family of findings:** the plan centers on publishing one `playback_snapshot` per tick from a `PlaybackContext`-managed cache. Three independent defect families converge on that cache: lifecycle-coupling (different fields invalidate on different triggers), by-reference sharing (shallow copy aliases nested mutables), and revision-counter overloading (every mutation path bumps `_timeline_flag_revision`, which clears `TriggerRouterNode`'s fire-once ledger). These three families produce ~15 of the 35 unanimous findings.

---

## Confirmed Findings (4/4 agreement)

### Persistence schema & round-trip (unanimous — critical)

**UF-1 [CRITICAL] Schema-version key divergence defeats migration and its own test.** `B4`/`D1`.
The plan's migration uses `schema_version` (bare key). The shipped persistence layer at `src/photonic_synesthesia/integrations/show_plans.py:16` uses `_SCHEMA_KEY = "_schema_version"` (underscore-prefixed). After the rollout, payloads have both keys (since `save_show_plan` at `show_plans.py:101` unconditionally stamps `_schema_version: SCHEMA_VERSION`), migration never fires on real files, and the Task 5 integration test fabricates a "v1" plan by calling `save_show_plan` *after* the SCHEMA_VERSION bump — which stamps `_schema_version: 2`, so the migration path is literally dead. Additionally, the plan silently narrows `load_show_plan`'s return type from `dict | None` (`show_plans.py:61`) to `dict`, breaking every caller's `if persisted is None` guard.
*Archetype: A8 + A10.*
*Fix direction:* standardize on the existing `_schema_version` everywhere (read, write, test assertions). Write a dedicated v1-fixture helper that emits JSON with `_schema_version: 1` directly (or without the key) rather than routing through `save_show_plan`. Preserve `Optional[dict]` return or audit + update every caller in Task 1, not Task 5.

**UF-2 [HIGH] Migration version gate uses live constant, not literal.** `A6`/`C4`.
`_migrate_show_plan_v1_to_v2` is gated by `if version < SCHEMA_VERSION:` and stamps `payload["schema_version"] = SCHEMA_VERSION`. When SCHEMA_VERSION bumps to 3 in a future cycle, a valid v2 plan (`version == 2`) re-runs the v1→v2 migration. Same bug, two phrasings — unanimous across the panel.
*Archetype: A8 (direct, textbook).*
*Fix direction:* `if version == 1:` (or `if version < 2:`) for the gate; `payload["_schema_version"] = 2` (literal, not `SCHEMA_VERSION`) for the stamp.

**UF-3 [HIGH] Transient operator-intent overlays persist as authored show data.** `B6`.
`_refresh_operator_intents_locked` at `runtime_context.py:137` does `self.show_sections = sections` — it reassigns the authoritative list with intent-applied overlays. `apply_operator_intent` then triggers `_show_plan_payload_locked()` serialization of `self.show_sections` — so transient overlays become authoritative on restart/rebind. Kilo's R2 extend: on reload, the re-hydrated sections get re-processed by `_refresh_operator_intents_locked`, *double-applying* intents (compounding corruption across save/load cycles).
*Archetype: A10 + A11.*

### Invariant-vs-existing-code contradiction (unanimous — critical)

**UF-4 [CRITICAL] "`_refresh_operator_intents_locked` never assigns `self.show_sections`" invariant is false by construction.** `D2`.
The plan states (L451): "`self._refresh_operator_intents_locked()` must never assign `self.show_sections = ...` directly — it only mutates the already-assigned list in place." The current helper body at `runtime_context.py:137` is literally `self.show_sections = sections`. Every pre-existing path (`update_transport` line 155, `snapshot`, `update_show_section`, `apply_operator_intent`, `bind_track_metadata`) calls this helper. The invariant is false from the moment it's written; every downstream design decision that assumes "refresh never assigns" is built on a false premise. Kilo R2 called this "the most important finding in the entire review."
*Archetype: A2 + A13.*
*Fix direction:* either refactor `_refresh_operator_intents_locked` to mutate the list in place (index-wise write under a preserved list identity) and enumerate every call site to prove the invariant holds, OR weaken the invariant to "authored boundaries (start/end) never change outside `_replace_show_sections_locked`" and explicitly acknowledge that operator-intent refresh rewrites per-section content.

### Cache lifecycle & by-reference publication (unanimous — critical family)

**UF-5 [CRITICAL] `_snapshot_cache` mixes fields with divergent invalidation lifecycles.** `B2`.
The cache stores `{show_sections, timeline_flags, staged_look, operator_workspace}` and is invalidated only on `_timeline_flag_revision` change. But `show_sections` can be mutated by `_refresh_operator_intents_locked` without a flag-revision bump; `staged_look` is bumped via `transport_revision` only; `operator_workspace` depends on tags (which can change without flag boundaries moving — see UF-14). Any field changing under a different trigger than the cache key produces stale reads.
*Archetype: A4 + A7 + A9 + A15.*

**UF-6 [CRITICAL] `set_staged_look()` does not invalidate the snapshot cache.** `C1`.
The plan's `set_staged_look` bumps `transport_revision` only — does not null `_snapshot_cache` and does not bump `_timeline_flag_revision`. `snapshot()` gates its cache on `_timeline_flag_revision`, so the very next `snapshot()` call returns the pre-stage `staged_look`. The Task 5 integration test that reads `state["playback_snapshot"]["staged_look"]` after `set_staged_look` receives stale data — the feature appears broken.
*Archetype: A4 + A5.*

**UF-7 [CRITICAL] `active_scene_id` cached statically in the cache-miss branch.** `A2`.
`snapshot()` computes `operator_workspace = build_operator_workspace(active_scene_id=str(self.show_sections[0]["id"]))` inside the cache-miss path. Since that path only runs when authored state changes, `active_scene_id` is frozen to section-0's id across the entire playback and never updates as the playhead advances.
*Archetype: novel (stale derived state).*
*Fix direction:* derive `active_scene_id` dynamically from `self.playhead_seconds` in the cheap transport overlay at the bottom of `snapshot()`, outside the cache block.

**UF-8 [CRITICAL] `playback_snapshot` published by reference — any nested mutation poisons the cache.** `A4`/`B2`/`C8`/`D4`.
`snapshot()` returns `dict(self._snapshot_cache)` — a shallow copy whose nested `show_sections` / `timeline_flags` / `staged_look` / `operator_workspace` still alias the cache. `_publish_playback_snapshot()` then does `self._state["playback_snapshot"] = playback.snapshot()` — so every graph node receives a dict whose nested structures alias the PlaybackContext cache. Kilo R2 extended this: `commit_staged_look`'s `dict.update()` merge mutates the cached nested dicts *in place* via alias — the cache poisons itself even without a separate consumer mutation. "Read-only by convention" is prose, not a guard.
*Archetype: A7.*
*Fix direction:* either deep-copy the snapshot at the publication boundary (accepting the per-tick copy cost; wrap behind a `(timeline_flag_revision, playhead_bucket)` publisher-side cache to amortize), OR freeze nested structures via `types.MappingProxyType` so mutation raises `TypeError` at the offender.

### Revision counter / ledger contamination (unanimous — critical family)

**UF-9 [CRITICAL] `TriggerRouterNode` fire-once ledger cleared by unrelated mutations.** `C3`/`D3`.
The plan states `_timeline_flag_revision` bumps only when authored timeline flags change (L335–340, L411). `TriggerRouterNode` clears `_fired_ids` on revision change (L1173). But the plan's own code bumps the counter unconditionally in: `bind_track_metadata` (L556, even when bound flags are identical), `set_staged_look` / `commit_staged_look` (Task 4 Step 7), `_regenerate_selection` (L1758). Any operator staging a look mid-playback silently re-fires every already-fired flag — reproducing the exact regression the plan claims to close. Gemini R2: "clearing the ledger on non-playback events breaks the once-per-show guarantee."
*Archetype: A4 + A9.*
*Fix direction:* make `_timeline_flag_revision` a derived quantity — compute `new_hash = hash(tuple((f["id"], f["at_seconds"]) for f in self.timeline_flags))` inside `_replace_show_sections_locked` and bump the counter iff the hash changes. Remove every ad-hoc `self._timeline_flag_revision += 1`. Add an acceptance test: "stage a look mid-playback → flags seen earlier must NOT re-fire on the very next tick."

**UF-10 [HIGH] `commit_staged_look` double-increments the counter and double-invalidates the cache.** `C3`/`D8`.
`commit_staged_look` calls `_replace_show_sections_locked` (which bumps the counter + invalidates the cache), then the caller bumps the counter *again* and invalidates the cache *again*. First bump is fine; second one re-clears the TriggerRouter ledger on the same commit. Straightforward duplicate work with observable consequences.
*Archetype: A9.*

### Staged_look contract & merge correctness (unanimous — critical family)

**UF-11 [CRITICAL] Preview-only vs same-tick-runtime staging contracts are incompatible.** `B1`.
Task 3 Step 5b demands `staged_look` affects ILDA output within the same `graph.step()` after staging. Task 4 Step 7 declares `staged_look` strictly preview-in-UI and states the runtime graph reads `show_sections` only — "runtime nodes must not hot-swap from staged sidecar data." Every dependent task implements against one of the two contracts; they cannot both be true.
*Archetype: A5 (fast/slow path divergence — preview vs commit produce observably different runtime output).*
*Fix direction:* the safer choice is preview-only. Task 3 Step 5b should verify staged data appears in `playback_snapshot["staged_look"]` for UI preview but does NOT alter ILDA/DMX output until `commit_staged_look()` merges into `show_sections`.

**UF-12 [HIGH] `commit_staged_look` uses shallow `dict.update()` for potentially nested payloads.** `C5`/`B5`.
`commit_staged_look` merges staged `cue_recipe` / `laser_program` via `dict.update()` — shallow, drops deeply-nested operator-authored fields (e.g., `phasers` sub-structures, `laser_program.zones[i].{...}`). Separately, Task 2 Step 8 does `existing_cue_recipe["phasers"] = build_phaser_bundle(...)` — unconditional overwrite — directly contradicting Risk-reduction rule 3's preservation guarantee. Both are forms of the same policy violation.
*Archetype: novel (policy self-contradiction) + data loss.*
*Fix direction:* (1) deep-merge semantics for `commit_staged_look`, or enumerate the nested key paths that are allowed to be overridden; (2) pick a single policy for `phasers`: either derived-only (exclude from the preservation guarantee) or preservation-subject (use `setdefault`/missing-only semantics). Rule 3 currently promises both.

**UF-13 [HIGH] Staged-look observable-equivalence never tested.** `D13`.
The plan claims `staged_look` is preview-only but never writes a test proving that runtime frames are byte-identical with and without a staged look. Without such a test, any silent leak from `staged_look` into runtime output survives until a human notices the lighting is "off." Tightly coupled to UF-11 — the contradiction in UF-11 makes this test impossible to write until the contract is picked.
*Archetype: A5.*

### Task ordering (unanimous)

**UF-14 [HIGH] Task 1 imports `build_operator_workspace` from a module created in Task 4.** `B3`/`C2`.
Task 1's `snapshot()` implementation at Step 10/11b calls `build_operator_workspace(...)`, but `src/photonic_synesthesia/platform/operator_workspace.py` is not created until Task 4 Step 6. Task 1 cannot compile or pass its own test gate.
*Fix direction:* create a minimal `operator_workspace.py` stub in Task 1 with the final function signature and a trivial implementation (e.g., `return {"banks": []}`); replace with the full implementation in Task 4. Option alternative: move all operator-workspace generation to Task 4 and leave `snapshot()` free of the key until then.

### Lock-scope correctness (unanimous)

**UF-15 [CRITICAL] Persistence completes outside the lock held for memory mutation.** `A1`/`D11`.
`replace_show_sections` / `set_staged_look` / `commit_staged_look` all acquire `_lock`, mutate memory, then drop the lock before `_persist_show_plan(payload)`. Two concurrent web-panel writers can both acquire sequentially (A then B), both drop the lock before writing to disk, and OS thread scheduling can place A's disk write *after* B's — leaving disk state at A while memory state is at B. Classic last-writer-loses.
*Archetype: A4.*
*Fix direction:* either place `_persist_show_plan` inside `_lock` (accepting blocking-I/O-under-lock cost on the 60Hz tick thread), or introduce a dedicated `_persistence_lock` acquired alongside `_lock`, or push payloads to a serialized background writer queue.

**UF-16 [HIGH] `bind_track_metadata` mutates `self.staged_look` outside the lock scope it nominally holds.** `D7`.
The plan's `bind_track_metadata` hydration (Step 12b) calls `_replace_show_sections_locked` under the lock, then mutates `self.staged_look = persisted.staged_look` — but that mutation is structurally outside the locked region. Concurrent reads see a torn state: new `show_sections` with old `staged_look`.

### Retrofit target correctness (unanimous)

**UF-17 [HIGH] Snapshot-read retrofit targets `__call__` but the real call lives in `_current_program_look()`.** `A3`.
Task 3 Step 5b instructs the implementer to replace `get_shared_playback_context().snapshot()` inside `ILDAOutputNode.__call__` / `MovingHeadControlNode.__call__`. Verified: the call is at `src/photonic_synesthesia/graph/nodes/ilda_output.py:263` and `src/photonic_synesthesia/graph/nodes/fixture_control.py:489`, both inside `_current_program_look(self, state: PhotonicState)`. An implementer searching `__call__` finds nothing; a conservative reading leaves the mid-tick, un-synchronized read in place, defeating the single-publish invariant.
*Fix direction:* update the instruction to modify `_current_program_look()` directly: `snapshot = dict(state.get("playback_snapshot") or {})` replacing the global-context call. Apply symmetrically to both files.

### Schema ordering (unanimous)

**UF-18 [HIGH] `_replace_show_sections_locked` honors caller-supplied `timeline_flags=` computed *before* intent refresh.** `D5`.
The plan fixes cycle-2 finding C3 by calling `_refresh_operator_intents_locked()` before `derive_timeline_flags(self.show_sections)`. But the helper's body is `self.timeline_flags = copy.deepcopy(timeline_flags if timeline_flags is not None else derive_timeline_flags(self.show_sections))` — if a caller passes `timeline_flags=X` (e.g., Task 2 Step 9's `self.replace_show_sections(resolved_sections, timeline_flags=timeline_flags)`, computed outside the lock on pre-refresh sections), the helper skips derivation and stores pre-refresh flags. The invariant is bypassed whenever an explicit `timeline_flags` is provided.
*Archetype: A1 + A4.*
*Fix direction:* remove the `timeline_flags=` parameter from `_replace_show_sections_locked`. Always re-derive from `self.show_sections` after the intent refresh. Callers that want to preserve persisted flags should set `self._persisted_timeline_flags_hint` and have the helper prefer the hint only when its hash matches the freshly-derived hash.

### Multi-fixture & coordinate safety (unanimous — HIGH cluster)

**UF-19 [HIGH] `LaserZoneRuntimeNode` brightness math is unclamped.** `D9`.
The brightness formula assumes cap ∈ [0, 1] and does not bound-clamp the resulting int before it hits DMX output. A cap > 1 or < 0 produces out-of-range DMX bytes. For physical fixtures this is a safety concern, not just a bug.
*Fix direction:* `brightness = max(0, min(255, round(cap * 255)))` at the output boundary. Add a property-based test that feeds caps from [-1, 2] and asserts output is always in [0, 255].

**UF-20 [HIGH] `LaserZoneRuntimeNode` "protected and y < 0" is coordinate-system-brittle.** `D10`.
The blank rule assumes screen-up-is-positive-y and that the stage floor is at y=0. For geometries where y grows downward, the wrong half blanks; for off-center rigs, y=0 isn't the stage floor. Codex R2: "hard-coding a stage split at `y < 0` bakes in one coordinate convention and one floor origin."
*Fix direction:* promote the blanking half-plane to a configured per-fixture attribute (e.g., `protected_half_plane: {axis: "y", threshold: 0.0, below_is_protected: True}`) or derive it from zone geometry rather than hardcoding.

**UF-21 [HIGH] `MovingHeadControlNode` / `PanelControlNode` index `[0]` without fixture-id filtering.** `D16`.
Both new consumers read `preposition_targets[0]` / `surface_layers[0]`. A multi-fixture rig gets cross-contamination: fixture #2 receives fixture #1's commands.
*Fix direction:* each target/layer dict should carry a `fixture_id` (or `fixture_type`) field, and nodes should filter by their own fixture identity before consumption.

### Integration-test fixtures & coverage (unanimous — HIGH cluster)

**UF-22 [HIGH] Task 5 integration fixture is non-constructible.** `D6`.
Fixture calls `PlaybackContext(session_id=..., file_name="fixture.mp3", duration_seconds=60.0, ...)`. Verified: real field order at `runtime_context.py:59–93` — `file_path: str` is the first required positional field (line 59) with no default; the fixture never passes it. Construction raises `TypeError: missing 1 required positional argument: 'file_path'`. The fixture also never registers `_metadata_bind_callback`, so the test calling `ctx.bind_track_metadata(...)` raises `RuntimeError("Playback metadata binding is not configured")` at `runtime_context.py:381`.
*Fix direction:* add `file_path="demo.wav"` (or `str(tmp_path / "demo.wav")`) to the fixture. Register a fake `_metadata_bind_callback` that returns its argument unchanged.

**UF-23 [HIGH] `@dataclass(slots=True)` + ad-hoc test mocks collide silently.** `D15`.
Verified at `runtime_context.py:55`. The plan adds five new runtime fields; none of the test fixtures opt into the slots layout, so any mock substitution that sets ad-hoc attributes will raise `AttributeError` at runtime rather than silently shim.
*Fix direction:* fixtures construct real `PlaybackContext` instances (after UF-22 fix) rather than using ad-hoc mocks; if mocks are needed, they must use `spec=PlaybackContext` to opt into the slots layout.

**UF-24 [HIGH] Fixture-bodies missing for `SurfaceCompositorNode` and `LaserZoneRuntimeNode`.** `C6` (Codex R2 dissent, included as majority).
Plan lists `tests/unit/test_surface_compositor.py` and `tests/unit/test_laser_zone_runtime.py` in the "Tests to create" list but never provides test bodies for either node. Implementations would ship unverified.
*Codex R2 dissent:* "Missing concrete test bodies in a plan is a documentation gap, not automatically a shipping verification gap." Panel majority treats this as a real coverage gap given the plan's own Rule 6 ("tests must prove behavior, not key presence").

**UF-25 [HIGH] `resolve_show_sections` acceptance test already passes before implementation.** `D12` (Codex R2 dissent, included as majority).
The acceptance gate for the task is a test that the current code already satisfies — no red/green signal, and the task can be silently skipped.
*Codex R2 dissent:* "Without a stronger description of the current assertion, this is too specific to treat as a plan-level defect." Panel majority treats this as a real TDD failure: any acceptance test that passes before implementation is evidence of a missing behavior specification.

**UF-26 [MEDIUM] Test bypasses node `__call__` boundary.** `A5`.
`test_moving_head_preposition_slows_motion_in_breakdown` directly calls `node._generate_moving_head_commands(...)` with a hand-crafted `program_look`, bypassing `__call__` and proving the helper's math works, not that `state["preposition_targets"]` is wired through `__call__` correctly. Violates the plan's own Rule 6.
*Fix direction:* invoke `node(state)` directly with `state["preposition_targets"] = [{"preset": "fan_open"}]` seeded, then assert against the resulting `fixture_commands`.

**UF-27 [MEDIUM] Plan code snippets don't compile against current signatures.** `B7`.
Multiple "write failing test first" snippets in Tasks 2/3/5 don't compile against current call signatures. Red/green distinction is muddled when tests are red because the fixture is malformed rather than because the feature is absent.

### Construction-site & safety-mode enumeration (unanimous — MEDIUM)

**UF-28 [MEDIUM] `PlaybackContext` construction sites not fully enumerated.** `C7`/`D18`.
The plan names CLI hydration but omits web UI, headless, and test-fixture construction sites. Adding new required fields breaks uncovered sites at runtime.

**UF-29 [MEDIUM] Three divergent `safety_modes` lists will drift.** `D17`.
`_ZONE_POLICY_RULES` default in Task 3, Step 11b workspace builder, and the Task 2 recipe bundle each define their own `safety_modes` list. First drift produces inconsistent operator UI.
*Fix direction:* single authoritative list in a common constants module; all three sites import from it.

**UF-30 [MEDIUM] Operator-workspace cache invalidation misses tag-only edits.** `D14`.
Workspace content depends on section tags. The plan's cache invalidates only on `_timeline_flag_revision`, which bumps on boundary changes only. Tag-only edits (where flag boundaries stay put) leave the cached workspace stale.

**UF-31 [MEDIUM] Error handling for missing/stale `playback_snapshot` not uniform.** `C10` (Codex R2 dissent, included as majority).
The four new consumer nodes each implement their own fallback for a missing or stale snapshot. Divergent behavior across nodes under edge conditions.
*Codex R2 dissent:* "The lack of a shared helper is a maintainability concern, but this finding overstates it as a concrete defect." Panel majority notes that in a pipeline of four new nodes this-cycle plus four retrofit consumers, uniform semantics is the difference between diagnosable and non-diagnosable failures.

**UF-32 [MEDIUM] Web-panel endpoint test asserts on unspecified HTML anchor.** `D19` (Codex R2 dissent).
Task 4 Step 3 test expects `id="operator-workspace"` in `response.text`, but the plan never specifies which template is modified or where the anchor is injected.
*Codex R2 dissent:* "The exact DOM anchor location is an implementation detail better driven by the acceptance test than fixed in the plan." Panel majority: without a template specification, the test is either magic or trivially fails.

### Trigger router policy (unanimous — MEDIUM/LOW)

**UF-33 [MEDIUM] `TriggerRouterNode._fired_ids` is in-memory only.** `C9` (Codex R2 dissent).
Every persisted timeline flag re-fires after process restart or `uvicorn --reload` — operationally the entire queue of already-fired flags arrives at start-of-day. Kilo R2 extend: during `uvicorn --reload` the re-fire storm is simultaneous and can overwhelm downstream DMX buffers.
*Codex R2 dissent:* "Exactly-once flag delivery across process restarts is a separate product requirement, not an obvious defect in this plan." Panel majority: the plan explicitly frames the fire-once guarantee as a correctness invariant (L411, L1173); reopening it on every process restart contradicts that framing.
*Archetype: A11 (operational semantics).*

**UF-34 [MEDIUM] `state["trigger_events"]` append-only across nodes invites dedup races.** `C12` (Codex R2 dissent).
If multiple nodes emit events for the same flag (or a node fires twice in a tick), the consumer sees duplicates with no dedup discipline.
*Codex R2 dissent:* "Duplicate `trigger_events` are only a bug if downstream semantics require uniqueness, which is not established here." Panel majority: asymmetric consumer behavior across duplicated events is a finding regardless.

**UF-35 [LOW] Brightness scaling uses `int()` truncation rather than `round()`.** `C14` (Codex R2 dissent).
Systemic bias: truncation always rounds down, producing slightly dimmer output than the cap intends.
*Codex R2 dissent:* "`int()` versus `round()` is a policy choice unless the plan requires symmetric brightness rounding." Panel majority: bias-free rounding is the default expectation for DMX scaling.

### Miscellaneous (unanimous — MEDIUM/LOW)

**UF-36 [MEDIUM] "Refresh must not assign" invariant has no guard or test.** `C11` (Kilo R2 dissent — but dissent strengthens, not weakens, the finding).
*Kilo R2 dissent:* "D2 demonstrates the invariant is already false by construction; the issue isn't missing enforcement but that the existing code contradicts the plan's stated invariant outright." Panel majority: UF-36 and UF-4 are the enforcement and root-cause sides of the same contradiction. Both are retained to make the fix scope explicit: UF-4 closes the contradiction, UF-36 prevents regression.

**UF-37 [LOW] Integration test imports private `_migrate_show_plan_v1_to_v2`.** `C13` (Claude R2 dissent).
Tests should drive through public `load_show_plan` which runs the migrator transparently.
*Claude R2 dissent:* "Reaching into `_migrate_show_plan_v1_to_v2` for a migration test is normal; the real boundary issue is the key mismatch (UF-1)." Panel majority agrees UF-1 is load-bearing; UF-37 is cosmetic once UF-1 is fixed. Included at LOW.

---

## Majority Findings (3/4 agreement)

All 10 dissents are noted under their parent finding above (UF-24 through UF-37 tagged with `(Codex R2 dissent)` / `(Claude R2 dissent)` / `(Kilo R2 dissent)` inline). No separate section — each reviewer's counter-claim is preserved verbatim alongside the finding.

---

## Split Findings (2/4 — manual review needed)

None this cycle. Every R1 finding cleared 3/4 or better in R2.

---

## Singleton Findings (1/4 — deeply verified only)

These emerged in R2 NEW sections from individual reviewers. Each was independently evaluated before inclusion.

**SF-1 [HIGH] `commit_staged_look` merges into `self.show_sections[active_idx]` but never recalculates `active_idx`.** Kilo R2.
If the playhead advanced between `set_staged_look` and `commit_staged_look`, the look commits into the wrong section. Verified in the plan: `commit_staged_look` (Task 4 Step 7) uses the `active_idx` captured at stage time. For show playback at 60 Hz with any non-instant operator commit, the index is almost certainly stale by commit time.
*Fix direction:* recompute `active_idx` from current `playhead_seconds` at commit time, OR fail the commit with a "section changed, please re-stage" error to preserve operator intent.

**SF-2 [HIGH] No rollback path if `_persist_show_plan()` fails after in-memory mutation.** Kilo R2.
A write failure after memory is mutated leaves memory and disk divergent with no recovery. Paired with UF-15 (persist-outside-lock), the plan's write path has neither ordering nor atomicity guarantees.
*Fix direction:* write to a temp file + atomic rename; on failure, revert the in-memory state (which requires snapshotting it before mutation) or mark the context "dirty-with-unpersisted-writes" and surface to the operator UI.

**SF-3 [HIGH] `PhotonicState` frame-local artifacts not explicitly cleared between ticks.** Claude R2.
If any node reads a prior tick's `preposition_targets` / `surface_layers` as a fallback, stale commands leak across frames.
*Fix direction:* make the pipeline's pre-tick reset authoritative — explicitly zero `preposition_targets`, `surface_layers`, `laser_zone_rules`, `trigger_events` at graph-tick entry. Add a test asserting no node's output depends on the prior tick's frame-local state.

**SF-4 [MEDIUM] `transport_revision` endpoint short-circuit missing.** Gemini R2.
Plan uses `transport_revision` for UI polling but never implements the endpoint logic to return `304 Not Modified` (or equivalent no-op) on unchanged revisions. The counter is useless without consumer support.

**SF-5 [MEDIUM] v1→v2 migration drops operator-workspace state.** Gemini R2.
If v1 plans contained operator-workspace state, the migration silently drops it. Less load-bearing than UF-3's finding that *transient* overlays persist; this is the converse (plausible operator state is lost on upgrade). Deprioritized because operator_workspace didn't exist in v1 — but if v1 saved any adjacent state the plan doesn't name, it's lost.

Not retained (held for post-cycle reconsideration):
- Codex R2 NEW: "published-once `playback_snapshot` needs a precise intra-tick publication point" — subsumed by UF-5/UF-8 and the cache-lifecycle family.
- Claude R2 N2: "no finding covers thread-safety of `TriggerRouterNode._fired_ids`" — true but the plan's single-threaded graph tick model makes this not-yet-applicable.

---

## Cross-Model Observations

**Where models converged (striking unanimity, 35 of 46 findings):**
- Persistence schema key mismatch: UF-1 cited by Codex, Gemini, Claude, Kilo with near-identical reasoning and independent file-line verification.
- Cache lifecycle family (UF-5/6/7/8): every reviewer independently flagged some flavor of the by-reference-publication + mixed-lifecycle bug.
- Revision-counter contamination (UF-9/10): all four reviewers independently traced the chain from mutation → counter bump → ledger clear → flag re-fire.

**Where models diverged:**
- Codex was the principal dissenter on "defense-in-depth" framings. Codex dissented on 7 of the 10 majority findings (C6, C9, C10, C12, C14, D12, D15, D19). Codex's pattern: narrower findings preferred, policy calls left to implementer, documentation gaps not treated as defects. This is a legitimate editorial position, not a blind spot — every dissenting counter-claim is preserved. The panel synthesizer (Gemini) sided with the majority in each case after evaluating the counter-claim.
- Claude R2 (fresh subagent) dissented only on C13 (private-migrator import), arguing UF-1 is the load-bearing version and UF-37 is cosmetic. Panel agreed and demoted UF-37 to LOW.
- Kilo R2 dissented only on C11, arguing UF-4 subsumes UF-36. Panel retained both because they scope distinct fixes (close-the-contradiction vs prevent-regression).

**Blind spots caught in R2 but missed in R1:** the cross-critique exposed two NEW findings that no single reviewer found in R1 but that the panel confirmed as real in synthesis: SF-1 (stale `active_idx` at commit time) and SF-3 (frame-local artifact clearance between ticks).

**Consensus false positives:** none detected. Every 4/4 finding validates against the actual plan text or a citable code location in the current repo.

---

## Provider Diagnostics

| Provider | R1 findings | R1 bytes | R1 elapsed | R2 | Notes |
|---|---|---|---|---|---|
| Codex (`gpt-5`) | 7 (2C/4H/1M) | 108,785 tokens | ~6 min | 46-vote, 1 NEW | Clean run. R2 sandbox (`sandbox_permissions=[]`) held — no file reads. Dissenter on 7 of 10 majority calls. |
| Gemini (`gemini-3.1-pro-preview`) | 6 (2C/2H/2M) | 9,620 chars | ~3 min | 46-vote, 2 NEW | Fallback chain returned first model on first attempt; no 429. |
| Claude (`opus-4.7`, subagent) | 19 (4C/12H/3M) | 119,110 tokens | 8 min | 46-vote, 2 NEW | Largest R1 volume; disqualified from self-synthesis per skill rule. Subagent correctly did spot-check file reads (≤10) to verify plan claims against real code. |
| Kilo (`z-ai/glm-5.1` via `kilo run --file`) | 14 (2C/5H/5M/2L) | ~83 KB JSONL | ~3 min | 46-vote, 2 NEW | PTY helper (`kilo_pty.py`) not present in skill dir — fell back to `kilo run --dir /tmp/mpreview_cycle1 --file r1_full.txt`. First attempt without `--dir` was blocked by kilo's `external_directory` guard; adding `--dir` resolved it. |

Panel was 4/4 throughout — no reviewer failed. Minimum-viable-panel rule (≥3 of 4) did not trigger.

**Orchestration notes for the next cycle:**
- Write `.claude/skills/multi-provider-review/kilo_pty.py` or update `SKILL.md` to document `kilo run --dir --file` as the primary path (not the PTY helper). The SKILL.md already notes "`kilo run` with `--file` arguments is the validated happy path as of cycle 3" — the PTY helper references should be treated as alternative, not primary.
- `/tmp` is outside kilo's default `external_directory` allowlist; `--dir /tmp/<workdir>` is required to scope kilo into the workdir.

---

## Proposed Catalog Additions & Logic-Vector Promotions

Per the skill's Step 7a: for every confirmed/majority finding, ask first whether it can be encoded as a deterministic L1 check. L1 has no cap; L3 is rent-controlled.

### Proposed L1 Logic Vectors

**L1-VECTOR-DRAFT: `cross-task-import-before-creation`** (from UF-14).
`rule_id`: `LOGIC-V233-cross-task-import-before-creation`.
Target file: new `code_auditor/code_auditor/checkers/v233_plan_ordering.py`.
AST walk: parse `docs/superpowers/plans/*.md` for markdown code fences labelled python. For every `from <module> import <symbol>` or `import <module>`, find the earliest `## Task N:` section the import appears under. For every `New files to create` list, extract the file path and find the earliest task where a `tests/... test_*.py` or the file itself is referenced. If an import appears in Task N's code but the source file is listed as "created in Task M > N," emit a finding with both line citations.
Severity: HIGH.
Category: `AuditCategory.PLANNING_ORDERING`.
Positive example: `Task 1` code `from photonic_synesthesia.platform.operator_workspace import build_operator_workspace` when `operator_workspace.py` is under "Task 4 creates".
Negative example: `Task 1` code imports only existing modules.
Caveat: works on plan markdown only; useless once code is merged (the import resolves).

**L1-VECTOR-DRAFT: `schema-version-gate-uses-live-constant`** (from UF-2).
`rule_id`: `LOGIC-V234-schema-version-gate-live-constant`.
Target file: new `code_auditor/code_auditor/checkers/v234_schema_version_gate.py`.
AST walk: find all `if <var> < <NAME>:` guards where `<NAME>` is an identifier that also appears as a write-side `payload[<key>] = <NAME>` stamp. Flag if the write side uses the same identifier (rather than an IntegerLiteral) in a function whose name contains `migrate` or `migration`. The archetype is "legacy fallback stamped with CURRENT constant" — variant of A8 already catalogued.
Severity: HIGH.
Category: `AuditCategory.SCHEMA_MIGRATION`.
Rationale: A8 already has a partial L1 vector (`LOGIC-V230-schema-version-default-is-constant`, per `lessons_from_missed_findings.md` L164). This extends it to migration gates specifically.

**L1-VECTOR-DRAFT: `persist-outside-lock`** (from UF-15).
`rule_id`: `LOGIC-V235-persist-outside-lock`.
Target file: new `code_auditor/code_auditor/checkers/v235_persist_outside_lock.py`.
AST walk: for every function containing a `with self._lock:` (or any `with <lock>:`) block followed by a call to a function named `*_persist_*`, `*_write_*`, `*save_*`, or `*serialize_*` *after* the `with` block closes, emit a finding. Variant: flag when a call to a method on a dataclass field of type `Lock` is released before the persistence call.
Severity: HIGH.
Category: `AuditCategory.CONCURRENCY`.
Caveat: high false-positive risk on read-only persistence calls. Mitigate by tracking which fields were mutated inside the `with` block and only flagging if the persisted payload sources from those fields.

**L1-VECTOR-DRAFT: `shallow-dict-snapshot`** (from UF-8).
`rule_id`: `LOGIC-V236-shallow-dict-snapshot`.
Target file: new `code_auditor/code_auditor/checkers/v236_shallow_dict_snapshot.py`.
AST walk: for every `return dict(self._<name>_cache)` or `return {**self._<name>_cache}` pattern in a function named `snapshot` / `published_*` / `publish_*`, emit a finding unless the returned dict is wrapped in `types.MappingProxyType` or every nested value is immutable (frozenset, tuple, int, str).
Severity: HIGH.
Category: `AuditCategory.SHARED_STATE`.
Rationale: defense-in-depth pattern (A7). The existing L3 catalog entry A7 has recurrence 1; this plan review is a second recurrence. Per the promotion rule (L3 entries with recurrence ≥ 2 AND deterministically encodable → promote to L1), A7 should be proposed for promotion. This draft is a first step.

### Proposed L3 Archetype Additions

**A16 — Contract invariant contradicted by the very code it's asserted over** (from UF-4).
- *Symptom*: a plan or docstring states an invariant like "function X never does Y," but the function's existing body does Y. The invariant is false by construction from the moment it's written; every downstream design decision that assumes the invariant is built on a false premise.
- *Mechanism*: plan authors write invariants against an imagined implementation without verifying against the actual code. Reviewers who read only the plan (not the code) miss the contradiction; reviewers who read only the code (not the plan) miss the invariant claim.
- *Detection hint*: for every invariant stated in prose ("must never X," "only bumps when Y"), grep for the subject of the invariant in the current code and verify the claim against every call site. Specifically: "never assigns X" → grep for `X = `. "Only bumps on Y" → grep for every site that mutates the counter and confirm Y is the precondition.
- *First seen*: Professional Lighting Feature Rollout Plan cycle 1 (Claude R1 F2 / UF-4). `PlaybackContext._refresh_operator_intents_locked` invariant "never assigns `self.show_sections`" directly contradicted by `runtime_context.py:137`.
- *Recurrence count*: 1.
- *L1 promotion candidate*: NO. Requires per-invariant domain understanding (which identifier the invariant is about, which assignments "count"). Too context-dependent for a deterministic AST check. Stays in L3 as a forcing question.

**A17 — Index-zero read against a list that is semantically per-collection, not per-element** (from UF-21).
- *Symptom*: consumer code does `collection[0]` on a list whose elements are per-fixture / per-tenant / per-user. In the single-fixture (single-tenant, single-user) path the code works; in the multi-* path, the 0th element cross-contaminates.
- *Mechanism*: developer wrote the happy-path producer as "emit one element per collection" but the consumer pattern defaults to `[0]` indexing. The bug is invisible until a multi-* deployment surfaces it, often in production.
- *Detection hint*: for any list-typed field whose name suggests per-entity semantics (`targets`, `layers`, `commands`, `events`), flag every `<field>[0]` read. Require either an explicit entity-filter (`[x for x in field if x.id == entity_id]`) or a documented rationale that the first element is canonical for all consumers.
- *First seen*: Professional Lighting Feature Rollout Plan cycle 1 (Claude R1 F16 / UF-21). `MovingHeadControlNode` and `PanelControlNode` read `preposition_targets[0]` / `surface_layers[0]`.
- *Recurrence count*: 1.
- *L1 promotion candidate*: PARTIAL. Deterministic detection of `list[0]` reads is trivial, but filtering to the per-entity semantic case requires naming conventions or type hints. Deferred pending a naming convention decision or a second recurrence.

**No other new archetypes proposed.** Findings UF-1 through UF-3, UF-5 through UF-18, UF-19 through UF-35 all fit existing archetypes A1, A2, A4, A5, A7, A8, A9, A10, A11, A13 — recurrence counts bumped accordingly.

### Recurrence count updates

- A4 (Race timeline not drawn): **3 → 4** (new instance: UF-9 revision-counter contamination in a single-threaded graph-tick model with concurrent web-panel writers).
- A7 (Defense-in-depth against future code): **1 → 2** (UF-8 by-reference snapshot publication). This crosses the L3→L1 promotion threshold; `L1-VECTOR-DRAFT: shallow-dict-snapshot` above is the promotion draft.
- A8 (Version-aware code assumes the current version is eternal): **1 → 2** (UF-1 + UF-2 both are A8 variants). `L1-VECTOR-DRAFT: schema-version-gate-uses-live-constant` is the promotion draft.
- A9 (Tuning parameters drift out of mutual consistency): **1 → 2** (UF-10 double-bump of `_timeline_flag_revision` on commit path).
- A10 (Round-trip bug hidden by asymmetric schemas): **1 → 2** (UF-1 schema-key mismatch is a round-trip failure by a different mechanism).
- A11 (Operational semantics ignored): **2 → 3** (UF-33 `_fired_ids` in-memory-only across `uvicorn --reload`).

Per the skill's rule "L3 entries with recurrence ≥ 2 AND deterministically encodable MUST be proposed for L1 promotion instead of bumping their recurrence counter," A7 and A8 are proposed for promotion above. A4 and A9 remain L3 because their "deterministic encodability" is lower (race timelines and tuning-knob consistency resist pure AST detection).

---

## Recommended revision scope for cycle 2

The plan has ~35 unanimous findings plus 10 majority findings. Grouped by fix-family for the cycle-2 revision:

1. **Cache lifecycle rewrite** (UF-5, 6, 7, 8, 10, 13, 30, SF-3): one architectural decision drives the fix — either deep-copy at publication or `MappingProxyType` wrapping, plus single-source-of-truth revision-counter derivation.
2. **Revision-counter derivation** (UF-9, 10, 18, and follow-ons from UF-5 family): compute `_timeline_flag_revision` from a hash of the derived `timeline_flags`, not from a mutation-side side-effect.
3. **Staged-look contract pick** (UF-11, 12, 13): preview-only (panel's recommendation). Rewrite Task 3 Step 5b to not assert same-tick runtime effect.
4. **Persistence schema alignment** (UF-1, 2, 3, 5b, SF-2): standardize on `_schema_version`, use literal `2`, write v1 fixture directly (not via `save_show_plan`), preserve `Optional[dict]`, add atomic-write + rollback path.
5. **Invariant-vs-code reconciliation** (UF-4, 36): decide whether `_refresh_operator_intents_locked` mutates-in-place or reassigns; rewrite its body + every call site accordingly.
6. **Lock-scope fixes** (UF-15, 16, and SF-2): `_persistence_lock` or in-lock persistence; move `self.staged_look` mutation inside the locked region in `bind_track_metadata`.
7. **Retrofit target fix** (UF-17): edit Task 3 Step 5b to target `_current_program_look()` in both files, with explicit file:line citations.
8. **Task ordering** (UF-14): stub `operator_workspace.py` in Task 1.
9. **Multi-fixture & safety** (UF-19, 20, 21): fixture-id filtering; clamp brightness; configurable blank half-plane.
10. **Test quality** (UF-22, 23, 24, 25, 26, 27): fix `file_path` fixture, register `_metadata_bind_callback`, add test bodies for `SurfaceCompositorNode` and `LaserZoneRuntimeNode`, replace pre-passing acceptance test with a real red/green test, compile-check every snippet.
11. **Enumeration** (UF-28, 29, 32): list every `PlaybackContext` construction site + unify `safety_modes` into one module + specify the template anchor for `operator-workspace`.
12. **Policy nits** (UF-31, 33, 34, 35, 37, SF-1, SF-4, SF-5): uniform snapshot-error helper, persisted `_fired_ids`, dedup policy for `trigger_events`, `round()` for brightness, drive migration tests through public API, recompute `active_idx` at commit, implement endpoint short-circuit, document v1→v2 behavior for operator-adjacent state.

Recommended cycle-2 structure: Tasks 1 and 2 revised together for the cache + revision-counter fix (they're coupled); Task 3 revised after Tasks 1/2 land in the plan; Tasks 4 and 5 revised last. Re-run the panel on the cycle-2 plan before any implementation.
