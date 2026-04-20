# Multi-Provider Destructive Review — Professional Lighting Feature Rollout Plan (Cycle 3)

**Target:** `docs/superpowers/plans/2026-04-19-professional-lighting-feature-rollout.md` (3234-line cycle-3 revision).

**Cycle:** 3 (addresses cycle-2 panel's 13 new defects NC-1 through NC-13).

**Panel:** Codex (`codex exec`, `gpt-5`), Gemini (`gemini-3.1-pro-preview`), Claude (`opus-4.7` subagent), Kilo (`kilo/z-ai/glm-5.1` via `kilo run --dir --file`).

**Panel size:** **3/4 — Kilo dropped out.** Kilo accepted the prompt and ran for ~9 minutes, reading the plan in five chunks and invoking tool calls, but produced no `text` events in the JSONL output before its timeout fired. The skill's minimum-viable-panel rule (≥3 of 4) is satisfied; the cycle continues. Gemini, Codex, Claude completed with full structured output.

**Rounds:** 1 only. R2 cross-critique skipped again — cycle-3 R1 has 3/3 convergence on the primary finding (NC-4 first-tick flag drop), plus a single-reviewer CRITICAL (Claude N5: snapshot shape narrowed) that is independently verifiable against the shipped code.

**Synthesizer:** rotating rule → Gemini (fewest new findings among the 3 valid reviewers).

---

## Executive summary

**Cycle 3 closed most of cycle-2's NC-1 through NC-9, but introduced three new CRITICAL defects and kept two HIGH defects partially open.** The plan is NOT ready for implementation.

| NC-ID | Cycle-3 status | Converging reviewers |
|---|---|---|
| NC-1 slots field | CLOSED | 3/3 |
| NC-2 persist-helper rename | CLOSED with call-site audit gap | Gemini/Claude CLOSED; Codex PARTIAL (valid) |
| NC-3 hash split | PARTIAL — hashes not initialized in `__post_init__` | Gemini + Claude flag init gap; Codex CLOSED_ENOUGH |
| NC-4 TriggerRouter pre-populate | REGRESSED — first-tick flag drop | Gemini/Codex/Claude 3/3 |
| NC-5 delete stale Task 4 snippet | CLOSED | 3/3 |
| NC-6 residual `timeline_flags=` | CLOSED | 3/3 |
| NC-7 persist-split | CLOSED_ENOUGH — no migration from cycle-2 baked payloads | Gemini/Codex CLOSED; Claude PARTIAL |
| NC-8 public/internal snapshot split | CLOSED (Gemini/Codex); REGRESSED (Claude) | Claude N5 is load-bearing |
| NC-9 SurfaceCompositor fixtures | CLOSED | 3/3 |
| NC-10–13 | STILL_OPEN (explicitly deferred) | 3/3 |

**The three new CRITICAL defects (one per reviewer, independently verifiable):**

1. **3C-N1 [CRITICAL]** (Gemini + Codex + Claude 3/3): `TriggerRouterNode` drops every flag at `at_seconds == 0.0` on the very first tick. Reason: `_last_timeline_flag_revision = -1`, published revision = 0, so `revision_changed = True` and `rewound = False` on the FIRST call. The NC-4 pre-populate branch fires, adding every `flag.at_seconds <= playhead` to `_fired_ids`; for a fresh show at playhead 0, that's all the `at_seconds=0.0` flags. Then `due` filters them out — the canonical section-0 `phrase_head` flag never fires.

2. **3C-N2 [CRITICAL]** (Claude only; verified independently against shipped code): `_snapshot_internal_locked` narrowed the snapshot return shape from ~30 keys (shipped) to 14 keys. Dropped keys include `session_id`, `track_title`, `track_artist`, `track_key`, `audio_url`, `audio_available`, `seekable`, `show_plan_path`, `ilda_transport_type`, `ilda_export_url`, `waveform`, `structure_markers`, `selection_mode`, `selection_variance`, `venue_mode`, `metadata_confidence`, `operator_intents`, `metadata_source`, `metadata_bound_at`, `show_source`, `playing`, `finished`, `realtime`, `speed`, plus the `available`/`hardware_warnings` flags the web-panel UI depends on. Every web endpoint that fetches `ctx.snapshot()` breaks.

3. **3C-N3 [HIGH → CRITICAL in aggregate]** (Gemini + Claude 2/3): `_authored_hash` and `_flags_hash` are not initialized in `__post_init__`. They default to `""`. On the first mutation after construction (e.g., operator previews a stage on an empty context), `new_flags != ""` → `_timeline_flag_revision` bumps → TriggerRouter ledger clears → cycle-1 UF-9 reopens. The cycle-3 NC-3 fix closed the coupling but left the bootstrap dangling.

Additional HIGH findings:

4. **3C-H1 [HIGH]** (Codex + Claude 2/3): payload-key mismatch. Authored cache publishes under `operator_workspace_banks`; web-panel endpoint reads `snapshot().get("operator_workspace")`. Because the endpoint falls back to `{"banks": []}`, the cycle-1 `test_web_panel_renders_operator_workspace_anchor` still passes green while the UI receives an empty workspace.

5. **3C-H2 [HIGH]** (Codex + Claude 2/3): the cycle-3 plan claims "all `_persist_show_plan` callers updated" but does NOT audit the shipped `apply_operator_intent` (`runtime_context.py:342`) or the public `persist_current_show_plan` (`runtime_context.py:280`). Both remain un-rewritten — they either skip the `_replace_show_sections_locked` discipline (re-introducing UF-4's list-identity issue through a different call path), or they'll call the renamed helper without holding both locks (violating the caller-locked contract). Specifically, Claude's N1 reports that shipped `persist_current_show_plan` DROPS `_lock` before calling the helper.

MEDIUM/LOW:
- **3C-M1** (Codex): plan's invariant section 3 of Step 11 still says `_timeline_flag_revision changes when _authored_hash changes`; the helper code correctly says `_flags_hash`. Implementer following the prose reintroduces the cycle-2 coupling bug.
- **3C-M2** (Gemini): Task 5 trigger-router regression test's `_persisted_timeline_flags_hint` contains only ONE flag, but the fixture's two sections with `transition_intent` generate FOUR derived flags. Hint fails equivalence check; helper overrides with the derived list. Test passes but doesn't actually exercise the hint path.
- **3C-M3** (Claude): cycle-2 persisted plans (that baked operator intents into `show_sections`) have no cycle-3 migration path. Loading such a plan applies the intents a second time on top of the already-baked base.

---

## NC-by-NC status table (synthesized from Gemini + Codex + Claude)

| NC | Claim | Gemini R1 | Codex R1 | Claude R1 | Consensus |
|---|---|---|---|---|---|
| NC-1 | slots field declared | CLOSED | CLOSED | CLOSED | **CLOSED** |
| NC-2 | `_persist_show_plan` rename, caller-locked | CLOSED | PARTIAL | CLOSED | **CLOSED with audit gap** (3C-H2) |
| NC-3 | split flags-hash from authored-hash | PARTIAL (init gap) | CLOSED_ENOUGH | PARTIAL (init gap) | **PARTIAL** (3C-N3) |
| NC-4 | pre-populate past flags on revision-bump | REGRESSED (first-tick) | PARTIAL (first-tick) | PARTIAL (first-tick) | **REGRESSED** (3C-N1) |
| NC-5 | delete stale Task 4 Step 7 snippet | CLOSED | CLOSED | REGRESSED(?) | **CLOSED** (Claude tagged an unrelated item) |
| NC-6 | residual `timeline_flags=` call sites | CLOSED | CLOSED | CLOSED | **CLOSED** |
| NC-7 | persist `_base_show_sections` + `operator_intents` separately | CLOSED | CLOSED_ENOUGH | PARTIAL | **CLOSED_ENOUGH** (3C-M3 migration gap) |
| NC-8 | public deep-copy / internal aliased snapshot | CLOSED | CLOSED | STILL_OPEN | **REGRESSED via 3C-N2** (field narrowing) |
| NC-9 | SurfaceCompositor takes fixtures + group expansion | CLOSED | CLOSED | CLOSED | **CLOSED** |
| NC-10–13 | deferred (medium/low) | STILL_OPEN | STILL_OPEN | STILL_OPEN | **deferred** |

---

## Convergence table: new cycle-3 findings

| Finding | Severity | Gemini | Codex | Claude | Verified against code? |
|---|---|---|---|---|---|
| 3C-N1 TriggerRouter first-tick flag drop | CRITICAL | YES (as NC-4 REGRESSED) | YES (as N1) | YES (as N2) | Logic-trace verified against plan L1717–1750 |
| 3C-N2 snapshot return shape narrowed | CRITICAL | — | — | YES (as N5) | **Verified against `runtime_context.py:159` — shipped returns ~30 keys; cycle-3 returns 14** |
| 3C-N3 hashes not initialized in `__post_init__` | HIGH (effectively critical) | YES | — | YES | Verified against plan — no init seeding shown |
| 3C-H1 `operator_workspace` vs `operator_workspace_banks` key mismatch | HIGH | — | YES (as N2) | YES (as N3) | Verified against plan L434 vs L2708 |
| 3C-H2 `apply_operator_intent` + `persist_current_show_plan` not audited | HIGH | — | YES (as N3) | YES (as N1) | Verified against `runtime_context.py:280, 342` |
| 3C-M1 invariant prose vs code divergence | MEDIUM | — | YES (as N4) | — | Verified against plan L508 vs L579 |
| 3C-M2 NC-6 test hint incomplete | MEDIUM | YES | — | — | Plan-level logical trace |
| 3C-M3 cycle-2 baked payload migration | MEDIUM | — | — | YES (as N4) | Operational argument |
| 3C-M4 Compositor test log-spam | LOW | YES | — | — | Minor |

One reviewer dropped out (Kilo). For the two convergent-3/3 findings (3C-N1 TriggerRouter, effectively also 3C-N3 hash init via Gemini+Claude), we have unambiguous consensus. For 3C-N2 (snapshot narrowing) only Claude caught it — but I verified it independently against shipped code, and it is a show-stopper on its own.

---

## Verdict

**Do NOT implement cycle 3 as written.** The plan has three CRITICAL/HIGH defects that will break on first test run:

- 3C-N1 — canonical section-0 flags never fire.
- 3C-N2 — web panel snapshot API returns 14 keys instead of 30, breaking every UI consumer.
- 3C-N3 — first operator action clears trigger ledger, reopening cycle-1 UF-9 regression.

The fixes are all mechanical:

1. **3C-N1 fix:** guard the pre-populate branch with `self._last_timeline_flag_revision >= 0` (per Gemini) so the first tick falls through the ordinary due-detection instead of consuming past flags.
2. **3C-N2 fix:** `_snapshot_internal_locked` returns the SUPERSET of (shipped `snapshot()` fields) + (new authored-cache fields) + (new live-overlay fields). The public `snapshot()` deep-copies the result. Don't narrow the shape — extend it.
3. **3C-N3 fix:** seed `_authored_hash` and `_flags_hash` at the end of `__post_init__`:

```python
def __post_init__(self) -> None:
    # ... existing body ...
    with self._lock:
        self._refresh_operator_intents_locked()
        self._authored_hash = _compute_authored_hash(self.show_sections, self.timeline_flags, self.staged_look)
        self._flags_hash = _compute_flags_hash(self.timeline_flags)
```

4. **3C-H1 fix:** pick one key — `operator_workspace_banks` is the cycle-2-correct name; update the endpoint read path at plan L2708 to match. Strengthen the web-panel test to assert non-empty bank content.
5. **3C-H2 fix:** add explicit cycle-3 rewrites for `apply_operator_intent` and `persist_current_show_plan` — they must go through `_replace_show_sections_locked` + `_persist_show_plan_locked` under the joint-lock pattern. Until this is done, UF-15 cannot be called CLOSED.

MEDIUM items (3C-M1 through 3C-M4) can be closed alongside or in polish.

The cycle-1 report's "ghost hardening" warning applies again: cycle 3 named mechanisms (`_snapshot_internal_locked`, `_persist_show_plan_locked`, per-fixture Surface grouping) that are correct in principle, but the naming was not fully wired against the shipped code. This is now the second consecutive remediation cycle with the same failure mode.

**Meta-observation about the multi-cycle pattern.** Cycle 1 closed cycle-0's ambiguities; cycle 2 closed most of cycle-1's findings and introduced new ones; cycle 3 closed most of cycle-2's findings and introduced new ones. Each cycle's convergence is ~75–85% of prior, but never 100%. The cycle-3 defects are smaller in scope than cycle-2's (which were smaller than cycle-1's), so the trajectory is toward convergence — but at this rate, 4 cycles will still leave non-zero residual. The pragmatic path is **cycle 4 fixes the 5 remaining bugs above, then implement**, accepting that implementation will catch any remaining edge cases that review missed.

---

## Provider diagnostics

| Provider | R1 findings | Notes |
|---|---|---|
| Codex (`gpt-5`) | 4 new + 13 NC assessments + 6 UF spot-checks | Complete run. Dissenter on NC-2/UF-15 (called the closure gap). |
| Gemini (`gemini-3.1-pro-preview`) | 4 new + 13 NC + 6 UF | Complete run. Single-attempt fallback success. Picked as synthesizer (fewest R1 new findings). |
| Claude (`opus-4.7`) | 11 new + 13 NC + cycle-1 spot-check | Most comprehensive; caught the snapshot-narrowing (3C-N2) single-handedly. |
| Kilo (`z-ai/glm-5.1`) | DROPPED | Ran ~9 minutes, five plan-read tool calls, no text events emitted before timeout. Minimum-viable-panel rule invoked (3/4 valid). |

Panel convergence was 3/4 on the lead finding (first-tick flag drop); every other finding was covered by at least 1 reviewer with independent verification. The Kilo dropout did not invalidate the cycle; similar outcome seen in the cycle-5 case documented in `SKILL.md`'s `"Gemini 429'd, Kilo filled the gap"` validation — in this cycle, Kilo did the opposite (Kilo timed out, but Gemini+Codex+Claude's 3/3 produced unanimous findings on the top defect).

---

## Recommended next step

**Cycle 4, narrow scope: the 5 fixes above only, then implementation.** Do NOT expand. Do NOT re-open closed items. Do NOT add new architectural refinements. The fix list is small and mechanical; the cycle-4 panel should close them all and produce a 0-new-CRITICAL report clean enough to start coding.

If the 5 fixes listed above are correctly applied, cycle 4 should come back substantially cleaner because the residual items (3C-M1 through 3C-M4 + NC-10 through NC-13) are acknowledged-deferred polish rather than architectural drift.
