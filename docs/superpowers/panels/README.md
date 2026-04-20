# Panel Reports

Consolidated outputs from the multi-provider destructive-review panel
(`multi-provider-review` skill: Codex / Gemini / Claude / Kilo, two rounds with
cross-critique, synthesized by the rotating-synthesizer model with the fewest
Round 1 findings).

Each report is the panel's verdict against the corresponding spec revision.

## Reports

| File | Spec revision | Synthesizer | Key result |
|---|---|---|---|
| `2026-04-18-runtime-context-cli-extraction-panel-report.md` | Cycle 1 — 177-line initial design | Codex (fewest R1 findings) | 12 confirmed / 4 majority / 3 R2-new. Original architectural findings: LOC target missing, import-migration absent, inverted-dependency claim, etc. |
| `2026-04-18-runtime-context-cli-extraction-panel-report-cycle2.md` | Cycle 2 — 353-line hardened revision | Gemini (fewest R1 findings) | 11/15 prior items closed or closed-enough; 4 PARTIAL. One new CRITICAL 3/4 (logic-ownership paradox). Most remaining issues were "ghost hardening" — naming mechanisms without operational definitions. |
| `2026-04-19-professional-lighting-feature-rollout-panel-report.md` | Cycle 1 — 2207-line plan for authored `showplan`, `playback_snapshot` publication, preview/commit staging | Gemini (fewest R1 findings) | 35 unanimous / 10 majority / 5 R2-new. Convergent critical families: schema-key divergence (`_schema_version` vs `schema_version`), cache lifecycle (`_snapshot_cache` mixes fields with divergent invalidation triggers), revision-counter contamination (every mutation bumps `_timeline_flag_revision`, re-firing `TriggerRouterNode` ledger), invariant-vs-code contradiction (`_refresh_operator_intents_locked` reassigns `self.show_sections` contrary to plan's stated invariant). Proposed 4 new L1 logic vectors (V233–V236) and 2 L3 archetypes (A16 invariant-vs-code, A17 index-zero-on-per-entity-list); promoted A7 and A8 to L1 drafts after recurrence-2 hit. |
| `2026-04-19-professional-lighting-feature-rollout-panel-report-cycle2.md` | Cycle 2 — 3026-line revision applying cycle-1 fixes | Gemini (fewest new findings) | 20–27 closed / 11–20 closed-enough / 2–6 partial / 1–8 still-open (deferred) / 1 REGRESSED (UF-15) + 13 new (4C/5H/3M/1L). "Ghost hardening" pattern: hash-derived counter + split cache + joint-lock named but mis-wired — `_persisted_timeline_flags_hint` not declared on slots class (NC-1), `_persistence_lock` deadlocks shipped `_persist_show_plan` (NC-2), hash still couples `staged_look`/tags to trigger ledger (NC-3), TriggerRouter thundering herd on ledger clear (NC-4), stale Task 4 Step 7 snippet regresses UF-7/UF-29 (NC-5), residual `timeline_flags=` call sites (NC-6), UF-3 overlays still bake into base on restart (NC-7), public `snapshot()` lost copy-on-read (NC-8), SurfaceCompositor group targets unaddressable (NC-9). Cycle 3 required before implementation. |
| `2026-04-19-professional-lighting-feature-rollout-panel-report-cycle3.md` | Cycle 3 — 3234-line revision applying cycle-2 fixes | Gemini (fewest R1 new findings; Kilo dropped out this cycle, 3/4 minimum-viable-panel) | 6–9 NC CLOSED / 1–2 CLOSED_ENOUGH / 1–4 PARTIAL / 4 STILL_OPEN (deferred) / 1 REGRESSED + 5 new (3C/2H/4M/1L). Cycle-3 ghost-hardening again: TriggerRouter first-tick drops `at_seconds=0.0` flags because pre-populate branch fires at `_last_timeline_flag_revision = -1` (3C-N1, 3/3 convergent); `_snapshot_internal_locked` narrowed return from ~30 keys to 14, breaking every web-panel consumer (3C-N2, Claude); `_authored_hash`/`_flags_hash` never seeded in `__post_init__` so first mutation clears trigger ledger (3C-N3); `operator_workspace` payload key mismatch between snapshot (`_banks`) and endpoint read (3C-H1); `apply_operator_intent` + `persist_current_show_plan` call sites not audited (3C-H2). Cycle 4 needs 5 narrow mechanical fixes before implementation. |
| `2026-04-19-professional-lighting-feature-rollout-panel-report-cycle5.md` | Cycle 5 (final gate) — 3551-line revision after cycle-4 fixes + cycle-6 surgical post-panel addendum | Gemini (fewest R1 new findings — found zero) | **READY_FOR_IMPLEMENTATION**. 4/4 panel; 3/4 verdicts READY (Gemini, Kilo, Claude); 1/4 FIX (Codex, with 2 HIGH + 1 MEDIUM + 1 LOW). All 6 cycle-4 defects CLOSED unanimously. Codex's 2 HIGHs (`request_seek` hash-recompute prose-only; `derive_timeline_flags` Task-1 stub missing) addressed via cycle-6 surgical post-panel fixes documented inline in the plan. Five-cycle review trajectory closed 76 unique defects total; ghost-hardening pattern stabilized in cycle 5. Cycle 4 panel report (omitted as separate file — covered in cycle-5 prose) is referenced inline. Plan is implementation-ready. |

## Method

The `multi-provider-review` skill (see `~/.claude/skills/multi-provider-review/`)
runs each provider in isolation (Round 1), then feeds each one the other
three's findings, anonymized (Round 2). The synthesizer is the model with the
fewest R1 findings — intended to reduce self-bias when consolidating.

Kept here as audit trail: these reports drove the three merged PRs that took
the extraction from plan → executed.
