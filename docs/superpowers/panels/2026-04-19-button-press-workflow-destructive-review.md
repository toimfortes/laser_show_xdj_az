# Destructive First-Principles Review — Button-Press Workflow After Catastrophic Crash

**Trigger:** user clicked "AI Assisted" selection mode while playing
`Darude - Sandstorm.mp3` via `photonic run-file ... --web --ilda-transport memory`.
Result: Python segfault + system-wide unresponsiveness, force reboot
required.

**Audit context:** `code_auditor audit --quick` reports 39 HIGH type
errors (mostly "returning Any" — pre-existing, non-load-bearing).
Lint clean. Tests green (272/272 unit + integration pass).

**Scope:** the click → web_panel.py endpoint → PlaybackContext
mutation → graph tick interaction chain, looking for thread-safety,
resource-exhaustion, lock-contention, and observability defects that
could explain the crash AND any other latent bugs in the same family.

---

## Executive summary

**Five critical defects, any one of which could have caused the crash,
and which together compound into a system-killing failure mode under
operator action during live playback.** Plus three high-severity
defects in the surrounding workflow.

The five-cycle plan review caught the architectural shape but did NOT
catch these because every cycle ran AGAINST THE PLAN, not against the
running system. The plan's "performance check" estimates assumed
~20 KB authored state; production-realistic state is **3-4× larger**
(measured 72 KB for a 30-section show with rich `laser_program`
payloads); under sustained 50 Hz update_transport that's a real CPU
burn, but it's the lock-during-IO defect (D2 below) that explains the
catastrophic OS-level failure.

---

## D1 — [CRITICAL] Zero observability across all 36 web-panel endpoints

**Location:** `src/photonic_synesthesia/ui/web_panel.py` — every
`@app.get/post/patch/put/delete` handler in the file.

**Claim:** None of the 36 HTTP endpoints log a single line. Not entry,
not exit, not exception, not the request payload. When the user's
system crashed, there was zero telemetry to identify which endpoint
was active, which PlaybackContext method was running, what payload
triggered it, or what state was held under which locks.

**Evidence:** automated audit (`grep 'logger\.|logging\.' web_panel.py`
restricted to handler bodies) returns 0 hits across all 36 endpoints.
Verified by inspection: handlers use `raise HTTPException(...)` to
bubble errors but `RuntimeError` from PlaybackContext methods is the
only "log signal" — and even that goes to stderr only because
HTTPException renders the message in the response body, NOT to a
configured logger.

**Why this is the critical finding:** observability is a prerequisite
to debugging the segfault. Without it, every other defect below is
*inferred* rather than *measured*. The user's terminal output shows
only `INFO: 127.0.0.1 - "GET /api/mock/playback HTTP/1.1" 200 OK` —
uvicorn's access log, NOT application telemetry.

**Fix:** add structured entry/exit/error logging to every endpoint.
Use the existing `logger = get_logger(__name__)` pattern (already
present in `runtime_context.py`, `staging_lane.py`, etc.).
Specifically:

- **Before any PlaybackContext call**: `logger.info("op", endpoint=..., section_id=..., mode=...)`.
- **In every except clause**: `logger.exception("op_failed", endpoint=..., error=str(exc))`.
- **For long-running ops** (regenerate, persist, bind_track_metadata):
  log entry + duration on exit so you can see lock-hold time.

Estimated effort: 1 hour with a templated decorator (`@log_endpoint`).

---

## D2 — [CRITICAL] Disk I/O held under `playback._lock` blocks the 50 Hz graph tick

**Location:** `src/photonic_synesthesia/platform/runtime_context.py`
- `PlaybackContext._regenerate_selection` (Task 1 rewrite)
- `PlaybackContext.replace_show_sections`
- `PlaybackContext.bind_track_metadata`
- `PlaybackContext.set_staged_look` (Task 4)
- `PlaybackContext.commit_staged_look` (Task 4)
- `PlaybackContext.update_show_section`
- `PlaybackContext.apply_operator_intent`

**Claim:** Every write path now does the following pattern (per the
cycle-1-thru-5 panel-driven architecture):

```python
with self._lock, self._persistence_lock:
    self._replace_show_sections_locked(...)
    payload = self._show_plan_payload_locked()
    self._persist_show_plan_locked(payload)  # SYNCHRONOUS DISK I/O
```

`_persist_show_plan_locked` calls `self._save_callback(payload)`. The
callback is `_show_plan_payload_saver(track_key)` from
`ui/cli.py`, which routes to `save_show_plan` in
`integrations/show_plans.py`, which does:

```python
tmp.write_text(json.dumps(stamped, indent=2, sort_keys=True), encoding="utf-8")
os.replace(tmp, path)
```

That's **synchronous disk write of a 70+ KB JSON-serialized payload
while holding `playback._lock`.** On a slow disk, an XDG_DATA_HOME on
a network mount, or any disk under load, this can take 100s of ms.

Meanwhile, `PhotonicGraph._publish_playback_snapshot()` runs at the
top of every `step()` (50 Hz hard real-time) and acquires the SAME
`playback._lock` to call `_snapshot_internal_locked`:

```python
def _publish_playback_snapshot(self) -> None:
    playback = get_shared_playback_context()
    if playback is None:
        self._state["playback_snapshot"] = {}
    else:
        with playback._lock:                  # ← BLOCKS while regen holds lock
            aliased = playback._snapshot_internal_locked()
        self._state["playback_snapshot"] = copy.deepcopy(aliased)
```

If a regenerate runs at the same moment the graph tick wants the
snapshot, the graph tick blocks for the full duration of the disk
write. Frame overrun → audio xrun → librosa thread potentially calls
into a numpy buffer that's been GC'd because the graph tick is stalled
→ **segfault.**

**Why the cycle-5 panel didn't catch this:** the panel reasoned about
correctness (lock ordering, cache freshness) but NOT about the
operational consequence of holding a contended lock through
unbounded-latency I/O. The plan's "joint-lock pattern" is correct for
ordering; it's wrong for liveness.

**Fix (the right shape):** persistence MUST run outside the
`playback._lock` region. Cycle-0 shipped code did this correctly:

```python
with self._lock:
    self.<mutate_state>
    payload = self._show_plan_payload_locked()
self._persist_show_plan(payload)  # outside the lock
```

The cycle-1 panel introduced UF-15 ("persistence outside lock allows
concurrent web-panel writers to interleave their disk writes") and
the cycle-2 fix added `_persistence_lock` to serialize disk writes.
But the fix made BOTH locks held across persistence, which is strictly
worse for liveness than the original race. The right pattern is:

```python
with self._lock:                                  # short — memory only
    self.<mutate_state>
    payload = self._show_plan_payload_locked()
with self._persistence_lock:                      # serializes writers; not held by graph
    self._persist_show_plan(payload)
```

This serializes disk writes (closes UF-15) AND keeps `playback._lock`
hold time bounded to in-memory operations (closes D2). The graph tick
never blocks on disk.

This is a **regression introduced by the cycle-2 panel's NC-2 fix.**
The panel was right that `_persistence_lock` was needed; it was wrong
to nest both locks across the I/O.

---

## D3 — [HIGH] Per-tick hash recompute is 24× the panel's "negligible" estimate

**Location:** `src/photonic_synesthesia/platform/runtime_context.py`
`update_transport()` (line ~302).

**Claim:** Cycle-5 panel R1 (Gemini) estimated:

> Executing `_recompute_authored_hash_locked()` at 60 Hz within
> `update_transport` ... At ~20KB of authored state, this operation
> takes microseconds and falls well within the <1ms per tick budget.

Production-realistic measurement (30 sections with rich
`laser_program` payloads — sustain blocks, fills, launch/release
hooks, fixture_capability_graph, transition/preposition/surface
intents):

- **JSON material size: 71.8 KB** (3.6× the panel's estimate)
- **`json.dumps + sha1` per call: 0.49 ms** (5× the panel's estimate)
- **At 50 Hz: 24 ms/sec spent on hash recompute alone — 2.4% of one core**

Not catastrophic by itself. But combined with D2's lock-hold-during-IO
and the per-tick deep-copy of the same 70 KB payload in
`_publish_playback_snapshot`, the graph tick's CPU budget is
significantly squeezed during steady-state playback. If the OS
scheduler then deprioritizes the graph tick (because it's been
hogging CPU), audio xrun follows.

**Cycle-5 panel R1 (Codex)** flagged this exact concern as "Codex-MEDIUM:
snapshot publication 'atomicity' wording slightly stronger than actual
lock/copy sequence" but the cycle-5 remediation log dismissed it:

> the actual sequence (acquire lock → build aliased snapshot → release
> lock → deep-copy outside the lock) is race-free for graph readers
> under `_state_lock`. The wording in Task 3 Step 5 is left as-is;
> the implementer's task is to verify per-tick latency, not strict
> atomic-publication semantics.

That dismissal was wrong. The implementer-side latency check WAS the
load-bearing question, and we shipped without measuring it.

**Fix:**

1. **Don't recompute the hash on every transport tick.** Operator
   intent expiry is rare; checking on every tick is overkill. Track
   intent TTLs separately and only call `_recompute_authored_hash_locked`
   when at least one intent has actually expired:

   ```python
   def update_transport(...):
       with self._lock:
           ...
           expired_count = self._refresh_operator_intents_locked()
           if expired_count > 0:
               self._recompute_authored_hash_locked()
   ```

   `_refresh_operator_intents_locked` already filters expired intents
   from `self.operator_intents` — make it return the count of removed
   intents and only recompute the hash when that's > 0.

2. **Cache the authored-hash material's components separately.** A
   single show_sections section can be hash-stamped on rebuild;
   recomputing the full SHA1 of the entire authored state every frame
   is wasteful when only one field could possibly have changed.

---

## D4 — [HIGH] Concurrent `_default_show_sections` call from FastAPI thread

**Location:** `src/photonic_synesthesia/ui/cli.py:1640`
`_regenerate_show_sections` closure called from
`PlaybackContext._regenerate_selection`, which is invoked by
`update_playback_selection_mode` on the FastAPI thread.

**Claim:** When the user clicks "AI Assisted", the FastAPI thread
invokes `_default_show_sections(...)` to rebuild every section's
`cue_recipe` and `laser_program`. This builder uses deterministic
random sampling, hash-keyed pattern selection, and (for ai_assisted
mode) the semantic-profile-driven AI scorer. None of that is per-se
unsafe.

But the SAME `_default_show_sections` call path is also invoked at
startup on the main thread when the original sections are built from
markers. If the AI scorer's internal state — `_pattern_candidates`
caches, the random number generator's deterministic-key state, joblib
worker pools, or any module-level mutable state — is not re-entrant
or thread-safe, calling it from the FastAPI thread mid-playback can
corrupt internals.

**Why it's plausible for the segfault:** the user's crash was
reproducible only under "select AI Assisted while playing." Switching
to procedural is fast and known-safe. The AI scorer's specific code
path is the trigger.

**What I haven't verified:** the exact thread-safety profile of
`_ai_assisted_pattern_score`, `_pattern_candidates`,
`_stable_weighted_choice`. These should be reviewed for module-level
mutable caches OR called only from the main thread.

**Fix:** offload the regenerate to the main thread (or a dedicated
single-threaded executor) instead of running it on the FastAPI worker
thread. Pattern:

```python
# At app startup, create a single-thread executor for regen.
self._regen_executor = ThreadPoolExecutor(max_workers=1)

# In the endpoint:
@app.patch("/api/mock/playback/selection-mode")
async def update_playback_selection_mode(request):
    return await asyncio.get_event_loop().run_in_executor(
        self._regen_executor,
        playback_context.set_selection_mode,
        request.selection_mode,
    )
```

This guarantees only one regen runs at a time AND it never races with
itself across threads.

---

## D5 — [HIGH] `_default_show_sections` is not bounded — no timeout on AI scoring

**Location:** `src/photonic_synesthesia/showplan/sections.py`
`default_show_sections` and its dependencies.

**Claim:** If the AI scorer for a single section blocks (e.g.,
unexpected NumPy stall, GIL contention with audio_sense's librosa
calls, semantic profile contains a NaN that causes infinite loop in
softmax normalization), the `_regenerate_selection` lock is held
indefinitely. Combined with D2 (graph tick blocks on the same lock),
this is a **system hang**. Not a crash — a hang. But hangs become
crashes when the user reaches for sysrq or kills uvicorn forcibly.

**Evidence:** no `signal.alarm`, no `concurrent.futures.Future.wait(timeout=...)`,
no `asyncio.wait_for(...)` anywhere in the regen path.

**Fix:** wrap the regen in a hard timeout (5 seconds is more than
generous for any sane show length):

```python
import concurrent.futures
try:
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_default_show_sections, ...)
        regenerated_sections = future.result(timeout=5.0)
except concurrent.futures.TimeoutError:
    raise RuntimeError("Show regeneration timed out — falling back to current sections")
```

---

## D6 — [HIGH] No back-pressure on the rapid-fire `update_transport` call site

**Location:** `src/photonic_synesthesia/graph/builder.py`
`PhotonicGraph.run_loop` calls `step()` at the configured FPS;
`step()` indirectly calls
`PlaybackContext.update_transport()` via the audio_node integration.

**Claim:** `update_transport` is called every tick. With cycle-5's
hash recompute (D3) this is a significant per-tick cost. If the FPS
is bumped to 60 (default mock_sensors uses 50, but the live config
allows 60+), we're at 30 ms/sec on hash alone, plus snapshot
publication, plus the graph nodes. There's no skip-frame fallback —
if a tick takes >16ms, the next tick starts late, never catching up.

**Fix:** measure the per-tick budget under realistic load. If
`update_transport` regularly exceeds 1 ms, add frame-skipping for
non-essential updates (the operator-workspace bank refresh doesn't
need to run at 50 Hz; 5 Hz is enough for UI).

---

## D7 — [HIGH] No bounded queue for the operator-workspace polling loop

**Location:** `src/photonic_synesthesia/ui/static/mock_control_plane.js`
`startOperatorWorkspacePolling` (added by me in the Task 4 frontend
commit).

**Claim:** I wired the operator workspace to poll every 2 seconds. If
the server is slow to respond (because the graph tick is fighting for
locks), the polling fetches stack up — the browser issues request N+1
before request N has returned. Standard `fetch()` doesn't queue;
each call is independent. Under sustained server stalls, this means
dozens of in-flight HTTP requests accumulating in the FastAPI thread
pool, each holding an event-loop slot, none completing.

The same pattern likely exists for other pollers
(`startUniversePolling`, `startPlaybackPolling`) — I didn't write
those but should audit them.

**Fix:** simple lock to skip overlapping requests:

```javascript
let workspaceFetchInFlight = false;
async function refreshOperatorWorkspace() {
    if (workspaceFetchInFlight) return;
    workspaceFetchInFlight = true;
    try {
        const payload = await fetchOperatorWorkspace();
        renderOperatorWorkspace(payload);
    } finally {
        workspaceFetchInFlight = false;
    }
}
```

---

## D8 — [MEDIUM] No graceful degradation when PlaybackContext is None

**Location:** every endpoint in `web_panel.py` that does
`playback_context = get_shared_playback_context()`.

**Claim:** when no session is active, every endpoint either returns
404 (HTTPException) or returns an empty default. This is correct for
the application-level contract but leaves the operator UI stuck in a
"Loading workspace banks…" state forever (because the JS polling
keeps requesting and the response shape doesn't carry an
"unavailable" flag the UI can render distinctively from "loading").

**Fix:** add an explicit `available: false` field to the
no-session response shape so the UI can render "No active session —
load a track to populate banks" immediately rather than spinning
forever.

(The shipped `snapshot()` already returns `available: True`; I
followed the same convention in the new `/api/operator/workspace`
endpoint when no session is active.)

---

## What the user should do RIGHT NOW

In priority order, before the next live test:

1. **Patch D1** — add structured logging to every endpoint. Two-line
   decorator pattern; ~1 hour. Without this, the next crash is just
   as opaque as this one.
2. **Patch D2** — move `_persist_show_plan_locked` outside the
   `playback._lock` region; keep `_persistence_lock` as the
   serializer. ~30 minutes. This is the single most likely cause of
   the catastrophic crash.
3. **Patch D3** — gate `_recompute_authored_hash_locked` on actual
   intent expiry (return-count from `_refresh_operator_intents_locked`).
   ~30 minutes. Drops the per-tick CPU cost from 24 ms/sec to <1 ms/sec.
4. **Patch D4** — confirm AI scorer thread safety by reading
   `_pattern_candidates` and friends. If anything mutates module-level
   state, fix it OR offload regen to the main thread per D4's pattern.
5. **Patch D7** — add the in-flight-fetch guard to all three JS
   pollers.

Patches 1-3 should land **before any further live testing**. Patches
4-5 are insurance against re-occurrence.

The cycle-5 panel got the architecture right but did not catch these
because every cycle reviewed the *plan*, not the *running system
under load*. The crash is the first piece of evidence we have from
the running system; that evidence trumps every panel verdict.
