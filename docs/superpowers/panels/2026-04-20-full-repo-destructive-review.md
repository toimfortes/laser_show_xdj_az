# Full-Repo Destructive Review — 2026-04-20

**Target:** `main @ f427b9a` (22,368 src LoC + 10,167 test LoC, 371 passing tests)
**Reviewer:** Claude (self, not a panel)
**Scope:** first-principles audit across SAFE / CORRECT / EFFICIENT / HARMONIOUS / SMOOTH / CREATIVE / SECURE / MAINTAINABLE / OBSERVABLE / TESTABLE axes.

---

## Verdict: NEEDS_FIX_FIRST

Two HIGH findings both have clear fixes; one is a straightforward bounded-buffer change in `ilda_output.py`, the other is an authorization-consistency refactor across the web panel. Zero CRITICAL findings (all prior cycles' CRITICALs are pinned by tests). One MEDIUM laser-safety defense-in-depth gap to consider if the upstream refactor ever breaks the invariant chain.

---

## Findings

### [HIGH] Unbounded `_ild_timeline` growth + O(N²) disk writes on `--ilda-transport ild`
- **Axis:** EFFICIENT + SMOOTH (unbounded growth + quadratic I/O in the hot path)
- **Location:** `src/photonic_synesthesia/graph/nodes/ilda_output.py:565-583` in `ILDAOutputNode._export_frames`
- **Claim:** When the user runs with `--ilda-transport ild` (the real authoring-mode flag for producing a `.ild` export), every 50 Hz graph tick appends new frames to `_ild_timeline` AND re-encodes + writes the ENTIRE accumulated timeline to disk. Memory grows unbounded across the song; disk I/O is O(N²) over song duration.
- **Evidence:**
  ```python
  if self.config.transport_type == "ild":
      if self._export_path is None:
          return
      self._ild_timeline.extend(frames)
      self._export_path.write_bytes(encode_ild(self._ild_timeline))
      return
  ```
  At 50 FPS × 3 fixtures × 300 s song = 45,000 frames in memory; at tick N the per-tick write cost is proportional to N. A 5-minute song hits `_ild_timeline` sizes of tens of thousands of `ILDAFrame` dicts and re-serializes them all every 20 ms. Smoke tests have only exercised `--ilda-transport memory` (the early return at line 567), so the test suite doesn't catch this.
- **Fix:** Buffer + periodic-flush or flush-on-stop. Option A: write `.ild` once, on `stop()`, keeping `_ild_timeline` in memory (acceptable for short sessions, still bounded by song length). Option B: write incrementally by appending just the new frames in binary mode and keeping a lightweight index instead of re-encoding the full timeline each tick. Option A is simpler and matches ILDA file semantics (one file = whole show). Requires moving `_export_path.write_bytes` out of `__call__` and into `stop()`.
- **Archetype:** A12 (framework primitive trusted at face value — `encode_ild` is correct, but calling it every tick on the growing timeline is a misuse).

---

### [HIGH] Split authorization model — 22 of 31 mutation endpoints have NO auth
- **Axis:** HARMONIOUS + SECURE
- **Location:** `src/photonic_synesthesia/ui/web_panel.py` across `/api/mock/playback/*`, `/api/operator/*`, `/api/mock/rigs/*`, `/api/mock/fixtures/*`, `/api/mock/scene`, `/api/mock/masters` — 22 mutation endpoints with no session check. Only 9 `/api/control/*` endpoints call `require_control(session_id)`.
- **Claim:** The control-lease system is clearly intended as the authorization gate (only one "operator" holds control at a time), but it only gates a minority of mutation endpoints. A rogue browser tab, misbehaving extension, or localhost-visible script can hit `POST /api/mock/rigs/{name}/load`, `DELETE /api/mock/rigs/{name}?force=true`, `PATCH /api/mock/playback/selection-mode`, `POST /api/mock/playback/operator-intents`, etc. without holding a lease — mid-show.
- **Evidence:** Endpoint-to-auth mapping (generated from `web_panel.py`):

  | Auth | Count | Examples |
  |---|---|---|
  | `require_control` | 9 | `/api/control/arm`, `/blackout`, `/intensity`, `/scenes/launch`, etc. |
  | No auth | 22 | `PATCH /api/mock/playback/selection-mode`, `PUT /api/mock/rigs/{name}`, `DELETE /api/mock/rigs/{name}`, `POST /api/operator/commit`, `POST /api/mock/playback/operator-intents`, etc. |

  Additionally: `POST /api/control/lease/acquire` itself has NO auth. Any client can acquire the lease just by asking. The lease is "advisory" rather than authoritative.

- **Fix:** Pick an axis and apply consistently. Either (a) require a control lease on ALL state-mutating endpoints (promote to a decorator, cover the 22 gaps — biggest change but most defensible), or (b) document that the web UI assumes a trusted single-user localhost environment and collapse the lease system to a simpler "intent tracker" (smaller change, but drops the appearance of security). Recommend (a). For `POST /api/control/lease/acquire`, require an `X-Operator-Token` header matched against an env var or config setting so one-off scripts can't seize control.
- **Archetype:** A2 (cross-cutting invariant — "auth on mutations" — applied at the boundary the original PR touched, pre-existing peers silently violate).

---

### [MEDIUM] ILDA DAC output only checks local blackout flag, not `state["safety_state"]`
- **Axis:** SAFE (defense-in-depth)
- **Location:** `src/photonic_synesthesia/graph/nodes/ilda_output.py:723-727` in `ILDADACOutputNode.__call__`
- **Claim:** The DAC transport node only checks `self._blackout_requested` to decide whether to send blank frames. It does NOT cross-check `state["safety_state"]["emergency_stop"]` or `state["safety_state"]["laser_enabled"]`. The upstream `ILDAOutputNode._should_blackout` does consult `safety_state`, and the tick order ensures it runs first, so the invariant holds TODAY — but the DAC transport is trusting upstream unconditionally. A refactor that breaks the `ILDAOutputNode → laser_zone_runtime → laser_vector_interlock → ILDADACOutputNode` chain, OR a code path that ever produces non-blank frames after safety_interlock fires (e.g., a debug / preview / replay mode), reaches the DAC without the safety check.
- **Evidence:**
  ```python
  if self._blackout_requested:
      frames = [self._blank_frame_for_fixture(fixture) for fixture in self.ilda_fixtures]
      self._stream_frames(self._merge_frames_for_dac(frames))
  else:
      self._stream_frames(self._merge_frames_for_dac(state["ilda_frames"]))
  ```
  Compare with `ILDAOutputNode._should_blackout` at line 168-178 which DOES consult `safety_state`. The two checks are asymmetric.
- **Fix:** Make `ILDADACOutputNode.__call__` mirror `ILDAOutputNode._should_blackout`'s check. Read `state["safety_state"]` as a fail-closed gate BEFORE deciding to stream. On a laser controller, the output stage must independently verify safety, not trust an upstream that could be refactored or bypassed.
- **Archetype:** LS1 (laser-specific: code path can emit an ILDA frame without passing through the safety interlock on its own authority). A13 (invariant enforced at boundary but relaxed at inner layer).

---

### [MEDIUM] `safeText()` doesn't escape HTML despite being used in innerHTML interpolations
- **Axis:** SECURE (local attack surface, defense-in-depth) + MAINTAINABLE (misleading name)
- **Location:** `src/photonic_synesthesia/ui/static/mock_control_plane.js:159-161` defines `safeText`; used at 2411, 2567, 2984, 3698, 4026, etc. all inside `.innerHTML = ...` template strings.
- **Claim:** `safeText()` is a null-guard, not an HTML escape. User-controlled strings (`fixture.label`, `section.label` from show_sections, operator-workspace `button.label` which flows from show_sections) are interpolated into template literals assigned to `innerHTML`. Someone who can write a rig JSON file (local FS access) or inject a show-section label through any of the unauthenticated mutation endpoints above can place arbitrary HTML/JS in the DOM.
- **Evidence:** `safeText(value, fallback = "n/a")` only returns `String(value)` or the fallback; no escape. Rendered via `<strong>${fixture.label}</strong>` on line 2411 where `fixture.label` is unescaped and unsanitized by both the server (`update_fixture` only truncates to 80 chars) and the client. `show_section.label` flowing through `operator_workspace.py:41` into bank buttons also follows this pattern.
- **Fix:** Add a real `escapeHtml(s)` helper that maps `& < > " '` to entities, rename `safeText` to `safeTextOr` (null-guard only) and use `escapeHtml(safeTextOr(...))` at every innerHTML interpolation site. Alternatively, construct DOM nodes with `textContent` instead of `innerHTML` — more invasive but eliminates the whole class of bug. Server-side: add a character allowlist for `fixture.label` (letters, digits, spaces, basic punctuation) so saved rigs can't carry HTML.
- **Archetype:** A3 (framework feature — `innerHTML` — used without verification that all interpolated values are safe).

---

### [MEDIUM] Control-lease acquisition has no authentication
- **Axis:** SECURE
- **Location:** `src/photonic_synesthesia/ui/web_panel.py` `POST /api/control/lease/acquire`; `src/photonic_synesthesia/platform/authority.py:28-55` in `ControlAuthorityService.acquire`
- **Claim:** Any client that can reach the HTTP endpoint can acquire the control lease. The only gate is "no one else currently holds it" — and if someone does, the incoming client can just wait for the TTL to expire (default visible in the request object). The lease exists to prevent two operators from fighting over controls, not to prevent unauthorized operation — but with 22 other mutation endpoints already unauthenticated (see HIGH above), a hostile actor doesn't need the lease anyway.
- **Evidence:** `ControlAuthorityService.acquire` gates only on `self._lease is None` or expired; accepts the request as truth for `issuer_id` and `session_id`. No shared-secret check, no env-var token, no OS-user check.
- **Fix:** If the web panel is ever meant to be exposed beyond localhost, add an `X-Operator-Token` header matched against `PHOTONIC_OPERATOR_TOKEN` env var, and reject `acquire` without it. For localhost-only deployment, document this explicitly as a SECURITY NOTE in the README + CLI help. Pair this with closing the HIGH authorization gap.
- **Archetype:** A13 (invariant "only an authorized operator can acquire control" enforced nowhere).

---

### [LOW] `_recent_pads` in MIDI sense + `_still_streak` / `_last_lit_state` defaultdicts in laser vector interlock have no fixture-id cleanup
- **Axis:** EFFICIENT (slow leak on long sessions)
- **Location:** `src/photonic_synesthesia/graph/nodes/midi_sense.py:94` + `src/photonic_synesthesia/graph/nodes/laser_vector_interlock.py` (defaultdict instances)
- **Claim:** When a fixture is added and later deleted from a MockRigStore, per-fixture state accumulated in node-internal dicts (`_last_point`, `_still_streak`, `_last_lit_state`, `_lit_transition_timestamps`) is never reclaimed because the graph's fixture set is frozen at construction time. In practice fixtures are frozen in graph scope so this may not matter — but if `materialize_to_fixture_configs` is ever called to rebuild the graph on rig change, the old dicts persist across graph instances if the node instances are reused.
- **Evidence:** Nodes are instantiated once in `build_photonic_graph` with a fixed fixture list; per-fixture state keyed on `fixture.id` accumulates until process exit.
- **Fix:** Either (a) document that fixture sets are graph-scoped and changes require a full graph rebuild (current reality), enforced with an assert on `__call__`; or (b) add a `reconfigure_fixtures(new_fixtures)` method that explicitly drops stale keys. (a) is sufficient for the current architecture.
- **Archetype:** A11 (operational semantics — rig reconfiguration — not fully thought through).

---

### [LOW] `encode_ild` called with a mutable list reference in `_export_frames`
- **Axis:** CORRECT (edge case)
- **Location:** `src/photonic_synesthesia/graph/nodes/ilda_output.py:581`
- **Claim:** `encode_ild(self._ild_timeline)` reads `self._ild_timeline` while concurrent tick appends could mutate. Today this node is called synchronously from the main graph tick so no concurrency, but if the HIGH fix above moves writes to a background thread, the list must be snapshotted first.
- **Fix:** When implementing the HIGH fix, pass `list(self._ild_timeline)` or a tuple snapshot to the encoder. Pin with a test that runs concurrent extend+encode and verifies no `list modified during iteration` exception.

---

### [LOW] 36 endpoints wrapped by `@log_endpoint` but no rate limit on stderr / log file
- **Axis:** OBSERVABLE (log flood risk)
- **Location:** `src/photonic_synesthesia/ui/web_panel.py` `@log_endpoint` decorator
- **Claim:** A malicious or buggy client that hammers `POST /api/mock/fixtures` 1000 times/sec produces 2000 structured log lines/sec. At 500 bytes per line that's 1 MB/sec of log output. No throttling.
- **Fix:** Optional: add a sampled-logging mode behind a feature flag for noisy-normal endpoints. Not urgent.

---

### Archetype walk (L3 + LS)

- **A1** partial call-chain — Not applicable; new parameters in recent work are either NET-NEW (rig storage) or cross-verified (cycle-1 five-review plan).
- **A2** pre-existing peers ignored — **FLAGGED** as HIGH above (auth on 22 of 31 mutation endpoints).
- **A3** framework used outside happy path — **FLAGGED** as MEDIUM above (innerHTML + unescape).
- **A4** race timeline — Looked at `_lock` + `_persistence_lock` + `_REGEN_INFLIGHT` across concurrent web clients + graph tick. The split-lock persist pattern is sound (mutation under `_lock`, disk write under `_persistence_lock` only); the regen in-flight guard fails open (returns 409). No new race found.
- **A5** fast/slow divergence — No fast/slow pair identified.
- **A6** asymmetric error guards — Minor: `dmx_output.py:143,157` has `except Exception:` that logs but doesn't re-raise; peer call site also unguarded. No clear defect.
- **A7** defense-in-depth against future code — `MockRigStore.dump()` deepcopies (good). `PlaybackContext.snapshot()` deepcopies (good). Not flagged.
- **A8** version-aware legacy default — Verified `show_plans.py:112` uses literal `1`; `rig_storage.py:295` uses literal `1`. Both correct.
- **A9** tuning knob drift — `_REGEN_TIMEOUT_SECONDS=5.0` / client fetch timeout 10s / WS ping interval 30s / stall watchdog `max_silence=1.0` / heartbeat interval. No contradiction found, but a comment table documenting the relationship would help future changes.
- **A10** round-trip schema asymmetry — `PUT /api/mock/rigs/{name}` strips `_schema_version` and `saved_at` server-side (verified); re-POSTing a GET response is safe.
- **A11** operational semantics — **FLAGGED** as LOW above (fixture-id cleanup on rig rebuild).
- **A12** framework primitive trusted — **FLAGGED** as HIGH above (`encode_ild` called in the hot path).
- **A13** boundary-vs-inner relaxation — **FLAGGED** as MEDIUM (laser DAC) + MEDIUM (lease auth).
- **A14** sibling trigger exemption — No DDL/trigger context.
- **A15** cache-key race — No relevant cache key dimension.
- **LS1** ILDA safety bypass — **FLAGGED** as MEDIUM above (DAC doesn't cross-check state).
- **LS2** intensity/position clamps AFTER safety — `safety_interlock` clamps Y-axis (lines 276-298) BEFORE the fixture-commands are written to `dmx_universe`. Correct order.
- **LS3** watchdog timeout vs blackout round-trip — `SafetyMonitor.max_silence` default is 1.0 s; heartbeat watchdog 1.5 s. If a frame stalls, safety monitor detects at 1s, triggers blackout, DAC receives blank at the next tick (20 ms later). Round-trip is <<1s, well inside the watchdog. Correct margin.

---

### "What I specifically want you to try to break" — results

1. **Kill the main loop at 50 Hz** — Review A fixed `feature_extract`. No OTHER node has a remotely comparable cost (all < 2 ms on a 2 s buffer in the probe). Didn't find a new killer.
2. **Concurrency** — `_lock` / `_persistence_lock` / `_REGEN_INFLIGHT` — no new race found; existing tests pin the split-lock pattern.
3. **Laser safety bypass** — The ILDA chain is sound IF the upstream produces blanks correctly. The DAC doesn't independently verify (MEDIUM finding above). DMX path via `safety_interlock` is bulletproof.
4. **Fail-open audit** — `rig_storage.get_active_rig_name` clears stale pointers (cycle-1 C1 fix). `feature_extract` bg process crash raises `BrokenProcessPool` which is caught (cycle-4 fix). Missing librosa fails safe (dummy features). Missing Ether Dream fails closed (emergency frame loop). Missing `fixtures_dir` returns empty profile list. **Did not find a new fail-open.**
5. **Unbounded growth** — **FLAGGED** as HIGH above (`_ild_timeline`).
6. **Schema trap A8** — Both persistence layers use literal `1`. Pinned by tests. Clean.
7. **Operator-intent footgun** — `set_staged_look` → `commit_staged_look` → subsequent regen wipes staged_look (cycle-3 finding, fixed). Delete active rig + force=true atomically clears pointer (cycle-1 H2). No new ordering bug.
8. **3 a.m. debugging hole** — The `endpoint_request` / `endpoint_response` logs (cycle-4 LOW-1 closure) plus structured fields make oncall tractable. What's MISSING: graph-tick trace. There's `processing_times` on `state` per tick but no periodic dump — a crash during a tick doesn't tell you which node was active at the moment. **Minor gap:** on crash, log the last N `processing_times` snapshots so oncall can see what was running.

---

## Recommendations

Before continued feature work:

1. **Fix the HIGH `_ild_timeline`** — 20 lines of code, one test.
2. **Fix the HIGH authorization split** — either close the 22-endpoint gap (a decorator + 1 line per endpoint) or document/downgrade the lease system explicitly. ~2 hours.
3. **Close the MEDIUM LS1** — one `if state["safety_state"]["emergency_stop"] or not state["safety_state"]["laser_enabled"]:` check in `ILDADACOutputNode.__call__`. 5 lines + one test.
4. **Close the MEDIUM XSS surface** — `escapeHtml` helper + ~6 innerHTML sites. ~30 min.

After these four, re-run this review; I expect VERDICT: READY_FOR_CONTINUED_DEVELOPMENT.

---

## Suggested L3 → L1 promotions from this review

- **LS1** (ILDA output must cross-check `state["safety_state"]`) — AST-detectable: match any `__call__` on a node named `*Output*` or `*Transport*` that mutates `state["ilda_frames"]` OR calls `_stream_frames` but doesn't reference `safety_state["emergency_stop"]`. HIGH severity, laser-specific, universal lesson for this codebase.
- **Split authorization** — AST-detectable: match `@app.(post|put|patch|delete)` endpoints whose body doesn't reference `session_id` or `require_control`. MEDIUM severity, per-project configurable.
