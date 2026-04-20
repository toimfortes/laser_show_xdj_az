# Destructive Review Cycle 2 — Button-Press Workflow After Crash

**Date:** 2026-04-19
**Scope:** current HEAD, not the earlier postmortem assumptions
**Context:** second-pass destructive review after confirming that parts of the first review have already been implemented in code

## Executive Summary

The current system is in a better state than the first destructive review described. Three of that review's strongest claims are now stale:

- playback panel rerenders no longer destroy the browser audio element during selection changes
- persistence has been moved outside `PlaybackContext._lock` on the playback-mutating write paths inspected
- web-panel endpoints now have a `@log_endpoint(...)` decorator and a module logger

That said, the button workflow is still not safe enough to dismiss the incident class. The highest-risk residual problems are:

1. playback regeneration still blocks the embedded web server thread synchronously for up to the timeout window
2. the graph tick still depends on the same playback lock while regeneration performs large in-memory copy work
3. show-section range controls still flood the backend with un-debounced PATCH requests and force full playback rerenders
4. button logging remains incomplete for local-only UI actions and imprecise for path-parameter actions

I did **not** find evidence in the current code supporting the first review's stronger "Python segfault because PortAudio callback xrun during file playback" narrative. `run-file` uses `AudioFileSenseNode`, not the live `sounddevice` callback path.

## Findings

### 1. [HIGH] Selection changes still block the embedded web server thread synchronously

**Why this matters**

The selection-mode and selection-variance handlers are `async`, but they call synchronous playback methods that wait for regeneration to finish before returning. Regeneration is offloaded to a single-thread executor, but the request handler immediately blocks on `future.result(timeout=5.0)`. That means the embedded uvicorn server thread is occupied until regeneration completes or times out.

**Evidence**

- `serve_in_thread()` starts uvicorn in a single background thread: `threading.Thread(target=server.run, ...)`
- `/api/mock/playback/selection-mode` and `/api/mock/playback/selection-variance` call `playback_context.set_selection_*()`
- `_regenerate_selection()` waits synchronously on `future.result(timeout=_REGEN_TIMEOUT_SECONDS)`

**Files**

- [web_panel.py](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/ui/web_panel.py:1409)
- [web_panel.py](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/ui/web_panel.py:1047)
- [web_panel.py](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/ui/web_panel.py:1060)
- [runtime_context.py](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/platform/runtime_context.py:663)

**Impact**

- all other HTTP requests through the embedded server can stall behind regeneration
- websocket/live-state updates can appear frozen during regeneration
- the browser can look hung even if the graph thread is still making progress

### 2. [HIGH] The graph tick still contends on `playback._lock` while regeneration performs large in-memory copy work

**Why this matters**

Disk I/O is no longer inside `playback._lock`, which is good. But regeneration still holds `_lock` while:

- replacing authored show sections
- deriving timeline flags
- recomputing hashes
- building the persisted payload via multiple `copy.deepcopy(...)` calls

The graph tick must acquire the same lock every step in `_publish_playback_snapshot()`. So the worst current stall path is no longer "lock held during disk write"; it is "lock held during large in-memory copy and snapshot-prep work."

**Evidence**

- graph tick: acquires `with playback._lock:` before publishing `playback_snapshot`
- regeneration: under `_lock`, calls `_replace_show_sections_locked(...)` and `_show_plan_payload_locked()`
- payload builder deep-copies `_base_show_sections`, `metadata_confidence`, `operator_intents`, `timeline_flags`, `staged_look`

**Files**

- [builder.py](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/graph/builder.py:149)
- [runtime_context.py](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/platform/runtime_context.py:715)
- [runtime_context.py](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/platform/runtime_context.py:575)

**Impact**

- graph progress can still pause during large regenerations
- terminal progress output in `run-file` can still appear stalled because the CLI loop advances through `graph.step()`
- this remains a credible explanation for "terminal hanged" even after the disk-I/O fix

### 3. [HIGH] Show-section range controls still flood the backend with one PATCH per `input` event

**Why this matters**

Unlike fixture edits and master controls, show-section range inputs are not debounced. Every drag emits immediate backend writes, and every successful response triggers `renderPlayback()`. That is a high-churn path through snapshot generation, DOM teardown/rebuild, and persistence.

This is not the same control path as the selection-variance slider in the playback header, which only commits on `change`. It is a separate residual hazard that remains severe in the UI.

**Evidence**

- show editor binds `input.type === "range" ? "input" : "change"`
- handler calls `patchShowSection(...)` directly
- `patchShowSection(...)` calls backend PATCH then `renderPlayback()`
- fixture/master controls use timed batching instead

**Files**

- [mock_control_plane.js](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/ui/static/mock_control_plane.js:1239)
- [mock_control_plane.js](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/ui/static/mock_control_plane.js:717)
- [mock_control_plane.js](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/ui/static/mock_control_plane.js:2417)
- [mock_control_plane.js](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/ui/static/mock_control_plane.js:3700)

**Impact**

- browser jank under slider drag
- unnecessary snapshot/persistence churn
- elevated lock contention during editing-heavy sessions

### 4. [MEDIUM] Button logging is no longer absent, but it is still incomplete

**Why this matters**

The current backend does log endpoint entry/exit/error through `@log_endpoint(...)`, so the first review's "zero observability across all endpoints" claim is outdated. But the logging is still incomplete for actual button workflows:

- local-only buttons such as `Sync To Live` and `Follow Live` never hit a backend route and have no success-path logging
- `log_endpoint()` only extracts the first `BaseModel` request body, so route parameters like `section_id` and `fixture_id` are not captured in the decorator log context
- the root HTML route `/` is not decorated

**Evidence**

- logger/decorator exist in `web_panel.py`
- selection/playback/operator/control endpoints are decorated
- `log_endpoint()` captures only `BaseModel` values, not path parameters
- `sync-audio` / `toggle-follow` are local click handlers with no telemetry

**Files**

- [web_panel.py](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/ui/web_panel.py:36)
- [web_panel.py](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/ui/web_panel.py:39)
- [web_panel.py](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/ui/web_panel.py:1035)
- [mock_control_plane.js](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/ui/static/mock_control_plane.js:592)

**Impact**

- you can now tell that a playback endpoint ran, but not always which section/fixture it targeted
- local UI actions still leave no durable trail

### 5. [MEDIUM] The current persistence helper contract is internally inconsistent after the lock-scope fix

**Why this matters**

The write paths now call `_persist_show_plan_locked(payload)` under `_persistence_lock` only, which is the right liveness move. But the helper docstring still claims the caller must hold both `_lock` and `_persistence_lock`, and the helper mutates `self.show_plan_path` / `self.show_source` without `_lock`.

This is not the original crash, but it is a contract drift problem: the code's concurrency model and its stated discipline no longer match.

**Evidence**

- callers use `with self._persistence_lock:` only
- helper docstring still says "caller MUST hold both `self._lock` and `self._persistence_lock`"
- helper writes shared fields after save callback returns

**Files**

- [runtime_context.py](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/platform/runtime_context.py:605)
- [runtime_context.py](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/platform/runtime_context.py:725)
- [runtime_context.py](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/platform/runtime_context.py:780)
- [runtime_context.py](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/platform/runtime_context.py:869)

**Impact**

- future maintainers can easily reintroduce locking bugs by following the stale contract
- snapshot-visible metadata fields can change outside the primary playback lock discipline

## What The First Review Got Wrong

### A. The audio-reset bug is already fixed

`renderPlayback()` now preserves the existing audio element across rerenders when the track/source is unchanged.

**File**

- [mock_control_plane.js](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/ui/static/mock_control_plane.js:509)

### B. "Zero endpoint logging" is no longer true

Playback and control endpoints are decorated with `@log_endpoint(...)`.

**File**

- [web_panel.py](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/ui/web_panel.py:994)

### C. "Disk I/O under `_lock` blocks the graph tick" is no longer the current defect

The code now moves persistence outside `_lock` on the mutated paths inspected. The current residual risk is the lock held during large in-memory work, not synchronous file write.

**Files**

- [runtime_context.py](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/platform/runtime_context.py:388)
- [runtime_context.py](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/platform/runtime_context.py:724)

### D. The "PortAudio callback segfault" narrative is not supported for `run-file`

`run-file` wires `AudioFileSenseNode` into `audio_sense`. That node decodes from a preloaded numpy buffer and does not use the live `sounddevice` callback path.

**Files**

- [audio_file_sense.py](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/graph/nodes/audio_file_sense.py:26)
- [cli.py](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/ui/cli.py:1713)

## Current Best Hypothesis

The most defensible current explanation is:

1. operator changes selection mode / exploration
2. request enters the embedded uvicorn thread
3. regeneration runs through the executor path, but the handler blocks waiting for it
4. authored-state swap and payload copy hold `playback._lock`
5. graph tick stalls on that lock long enough for the CLI to appear frozen
6. browser-side updates also appear frozen because the embedded server thread is busy

That explains:

- terminal appearing hung
- UI appearing hung
- prior audio interruption reports historically

without requiring a speculative segfault path that the current `run-file` code does not support directly.

## Residual Open Questions

- I did not reproduce the original force-reboot event in this pass.
- I did not prove whether the host-level lockup came from this process alone or from a broader system interaction such as GPU/audio/driver pressure.
- I did not benchmark current lock-hold duration during real regeneration on a large track payload.

## Recommended Next Instrumentation

1. Add lock-hold timing around `_regenerate_selection()`'s under-`_lock` phase.
2. Add graph-step timing around `_publish_playback_snapshot()`.
3. Add explicit frontend telemetry for `sync-audio`, `toggle-follow`, and section-jump buttons.
4. Debounce show-section range writes before further load testing.
