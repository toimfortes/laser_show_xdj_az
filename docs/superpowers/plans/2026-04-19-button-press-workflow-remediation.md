# Button-Press Workflow Remediation Plan

**Date:** 2026-04-19
**Incident:** catastrophic hang during live file playback after switching the playback selection engine to `AI-Assisted` and changing exploration range
**Primary audit artifact:** [docs/superpowers/panels/2026-04-19-button-press-workflow-destructive-review.md](../panels/2026-04-19-button-press-workflow-destructive-review.md)
**Automated audit artifact:** [data/code_auditor/summary.md](/home/antoniofortes/Projects/laser_show_xdj_az/data/code_auditor/summary.md)

## Scope

This document converts the crash audit into a remediation worklist. It is focused on the playback web UI, `PlaybackContext`, regeneration/persistence behavior, and graph-tick interaction during live playback.

## Confirmed Results

### 1. Frontend playback interruption is real and deterministic

Changing playback selection mode or exploration currently destroys and recreates the entire playback panel, including the `<audio>` element. That stops browser playback even when the backend request succeeds.

Affected path:

- `src/photonic_synesthesia/ui/static/mock_control_plane.js`
  - `renderPlayback()`
  - `updatePlaybackSelectionMode()`
  - `updatePlaybackSelectionVariance()`

### 2. Backend stall path is plausible and high-risk

The selection-mode and exploration endpoints call `PlaybackContext._regenerate_selection()`, which:

1. regenerates show sections synchronously
2. acquires `self._lock` and `self._persistence_lock`
3. mutates authored state
4. serializes the full show-plan payload
5. writes the payload to disk synchronously
6. returns a full snapshot

The graph tick also needs `playback._lock` before every step to publish `playback_snapshot`. That means a long regenerate/persist cycle can block the graph loop and make the runtime appear hung.

Affected path:

- `src/photonic_synesthesia/ui/web_panel.py`
  - `/api/mock/playback/selection-mode`
  - `/api/mock/playback/selection-variance`
- `src/photonic_synesthesia/platform/runtime_context.py`
  - `_regenerate_selection()`
  - `_persist_show_plan_locked()`
  - `snapshot()`
- `src/photonic_synesthesia/integrations/show_plans.py`
  - `save_show_plan()`
- `src/photonic_synesthesia/graph/builder.py`
  - `_publish_playback_snapshot()`

### 3. Success-path logging is missing for the button workflows

The UI mostly logs only failures via `console.error()` / `console.warn()`. The FastAPI handlers in `web_panel.py` do not emit structured entry/exit/error logs around playback actions. There is no durable event trail for:

- selection mode changes
- exploration changes
- sync/follow playback buttons
- scene launch buttons
- fixture add/remove/edit buttons
- operator stage/commit actions
- master intensity/speed/blackout controls

### 4. Fresh `codeauditor` result

Latest run summary:

- phases completed: 14
- total findings: 313
- critical/high/medium/low: 9 / 113 / 43 / 148
- CI fail reason: `Critical/high issues found in patterns`

Notes:

- The `patterns` failure is tool-integration debt: `check_patterns` emitted output the auditor could not parse.
- `tests` phase passed.
- The incident-specific risk is not explained by the type findings; the hang analysis is driven by the workflow review above.

## Root-Cause Hypothesis

### Primary operational failure

The operator action triggers a heavyweight synchronous regeneration path on the web server thread. That path holds the same playback lock needed by the graph tick. Under load, the graph stops making progress long enough that the terminal appears hung and playback state becomes inconsistent.

### Secondary user-visible failure

Even when the backend does not hang, the frontend forces playback to stop because it recreates the audio element after every successful mode/variance update.

### Diagnostic failure

The system does not log enough at the point of action to prove which of the slow paths was active when the stall occurred.

## Remediation Priorities

## P0

### Preserve audio across playback control refreshes

Goal: selection changes must not destroy current browser audio playback.

Required changes:

- stop rebuilding the `<audio>` element during ordinary playback metadata refreshes
- preserve `currentTime`, paused/playing state, and follow-mode state if a rerender is unavoidable
- split `renderPlayback()` into stable transport controls vs mutable metadata sections

Acceptance criteria:

- switching `selection_mode` from `procedural` to `ai_assisted` does not stop audio
- changing `selection_variance` does not stop audio
- waveform, status text, and active section still update correctly

## P0

### Remove long-running persistence from the critical lock window

Goal: graph step must not block on JSON serialization or file writes caused by UI mutations.

Required changes:

- shorten the `playback._lock` critical section
- move serialization and disk I/O outside the playback lock, or queue persistence asynchronously
- ensure snapshot publication can proceed while persistence is pending
- keep authored-state consistency guarantees explicit if the lock contract changes

Acceptance criteria:

- selection mode change during active playback does not stall graph stepping
- repeated exploration changes do not freeze CLI progress output
- the runtime continues publishing snapshots during persistence

## P0

### Add structured logging to all button workflows

Goal: every operator action that can affect playback, regeneration, persistence, or transport must leave an audit trail.

Required changes:

- add logger wiring to `src/photonic_synesthesia/ui/web_panel.py`
- log entry, exit, duration, and failure for playback-mutating endpoints
- add frontend success logging or explicit event reporting for major button flows
- include request context fields where applicable:
  - `session_id`
  - `track_key`
  - `selection_mode`
  - `selection_variance`
  - `section_id`
  - elapsed duration

Acceptance criteria:

- mode change produces at least one frontend event and one backend event
- variance change produces at least one frontend event and one backend event
- logs make it possible to identify the last successful and last failed button action before a stall

## P1

### Add regression tests for the incident path

Goal: the exact click sequence that triggered the incident must become a repeatable test case.

Required coverage:

- backend test for `set_selection_mode()` during active playback
- backend test for `set_selection_variance()` during active playback
- concurrency-style test proving graph snapshot publication is not blocked beyond a defined threshold
- frontend/browser test or equivalent integration test proving audio survives selection changes

Acceptance criteria:

- the incident sequence is covered by automated tests
- tests fail on audio element recreation regressions
- tests fail on lock-window regressions that stall graph progress

## P1

### Instrument regeneration and persistence latency

Goal: the system must expose how long regeneration and save paths actually take in production-like runs.

Required changes:

- time `PlaybackContext._regenerate_selection()`
- time `_show_plan_payload_locked()`
- time `_persist_show_plan_locked()`
- time `_publish_playback_snapshot()`
- emit warning logs for slow operations above a defined threshold

Acceptance criteria:

- logs show per-operation timing for selection changes
- slow-path warnings are emitted for abnormal lock hold times

## P2

### Clean up audit-tooling blockers

Goal: make future audits trustworthy and easier to compare.

Required changes:

- fix `scripts/check_patterns.py` output so `codeauditor patterns` parses cleanly
- build `data/code_catalog.json`
- review the high-value security findings separately from this incident

Acceptance criteria:

- `codeauditor audit --enforce` no longer fails on malformed pattern output

## Suggested Work Sequence

1. fix playback panel rerender behavior
2. reduce lock hold time in regeneration/persistence flow
3. add backend endpoint logging
4. add incident regression tests
5. add latency instrumentation
6. clean up audit-tooling integration issues

## Verification Plan

Run after remediation work:

```bash
pytest -q
ruff check src tests
mypy src
/home/antoniofortes/Projects/code_auditor/.venv/bin/codeauditor audit --project . --sarif-out data/audit/photonic_audit.sarif --enforce
```

Manual regression:

1. start `photonic run-file ... --web`
2. begin playback in browser
3. switch `Selection Engine` to `AI-Assisted`
4. change `Exploration`
5. confirm:
   - audio continues uninterrupted
   - CLI continues advancing
   - no terminal hang
   - logs show the action sequence with durations

## File Targets

- `src/photonic_synesthesia/ui/static/mock_control_plane.js`
- `src/photonic_synesthesia/ui/web_panel.py`
- `src/photonic_synesthesia/platform/runtime_context.py`
- `src/photonic_synesthesia/integrations/show_plans.py`
- `src/photonic_synesthesia/graph/builder.py`
- `tests/...` incident regression coverage

## Non-Goals

- resolving all existing type findings in this remediation pass
- resolving unrelated security findings unless they intersect the playback workflow
- changing the high-level authored-state model unless lock reduction cannot be achieved safely within the current design
