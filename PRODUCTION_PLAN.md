# Production-Readiness Plan: Photonic Synesthesia
**Revision:** Feb 2026 — Based on direct code audit
**Status:** Pre-production (safety-hardened alpha)

---

## 1. Current-State Assessment

### 1.1 Architecture

**Runtime model:** LangGraph directed graph executed in a synchronous step-loop (`run_loop`).
Three background threads (audio capture callback, MIDI callback, DMX TX at ~40 Hz) plus an independent heartbeat watchdog.

**Actual graph order (post-hardening):**
```
audio_sense → feature_extract → beat_track → structure_detect → fusion
midi_sense ─────────────────────────────────────────────────────┘  ↓
cv_sense ────────────────────────────────────────────────────────  ↓
                                                           director_intent
                                                                   ↓
                                              scene_select → {laser,moving_head,panel}_control
                                                                   ↓
                                                             interpreter (smoothing + strobe budget)
                                                                   ↓
                                                          safety_interlock (dual-layer clamping + watchdog)
                                                                   ↓
                                                            dmx_output (FTDI serial or Art-Net UDP)
                                                                   ↓
                                                                  END
```

### 1.2 What Is Actually Implemented

| Component | Status | Notes |
|-----------|--------|-------|
| LangGraph orchestration | ✅ Complete | `graph/builder.py`; 17 nodes wired |
| DMX serial (FTDI/Enttec) | ✅ Complete | `graph/nodes/dmx_output.py`; pyftdi optional |
| Art-Net UDP output | ✅ Complete | `dmx/artnet.py`; blackout-on-stop |
| DMX universe abstraction | ✅ Complete | `dmx/universe.py`; 513-byte contract tested |
| Audio capture | ✅ Complete | sounddevice ring buffer; graceful when absent |
| Feature extraction | ✅ Complete | librosa (RMS, spectral centroid, MFCCs, band energies); dummy fallback |
| Beat tracking | ✅ Complete (backends untested) | madmom/BeatNet + RMS fallback; backends conditionally imported |
| Structure detection | ✅ Complete | Heuristic drop/buildup/breakdown state machine |
| MIDI input | ✅ Complete (CC map unverified) | XDJ-AZ CC map hardcoded in `midi_sense.py:39-60` |
| CV screen capture | ✅ Functional (manual ROI) | mss + OpenCV template-match / Tesseract |
| Multi-modal fusion | ✅ Complete | BPM fusion 0.7 audio + 0.3 CV; energy derived from RMS + transient |
| Director / intent engine | ✅ Complete | Phrase-boundary gating; heuristic ML stream |
| Scene selection | ✅ Complete (no built-in scenes) | JSON-based; `config/scenes/` starts empty |
| Fixture control | ✅ Complete (hardcoded channel maps) | 7-ch laser, 16-ch moving head, 6-ch panel; no YAML profile loader |
| Interpreter / channel smoothing | ✅ Complete | max_delta_per_frame=36; strobe budget → DMX |
| Safety interlock | ✅ Production-hardened | Dual-layer Y-axis + speed clamps; heartbeat watchdog daemon |
| CLI (`photonic run/dmx_test/analyze`) | ✅ Production-hardened | SIGTERM/SIGINT → stop; finally on all exit paths |
| Web panel (`photonic-web`) | ❌ Stub only | Entrypoint exists; no routes, no WebSocket |
| Startup config validation | ❌ Missing | Fixture profiles, scene files not validated at startup |
| Scene library | ❌ Missing | `config/scenes/` is empty; user must author JSON |
| Fixture profile loader | ❌ Missing | Channel maps hardcoded in nodes, not loaded from YAML |

### 1.3 Dependency Health

| Group | Dependencies | Risk |
|-------|-------------|------|
| Core (always installed) | langgraph, langchain-core, pydantic, pydantic-settings, numpy, scipy, structlog, click, pyyaml | Low |
| Optional / graceful | sounddevice, librosa, opencv-python, mss, pyftdi, mido, python-rtmidi, madmom | Low — try/except guards on all |
| Optional / untested | BeatNet, torch (extra `[beatnet]`) | Medium — import conditional; backend logic untested |
| Not used yet | fastapi, uvicorn, websockets (extra `[web]`) | Low — planned only |
| Unresolvable in CI | madmom (native deps), sounddevice (audio hw) | Mitigated by `SDL_AUDIODRIVER=dummy` in CI |

**Pinning:** No `requirements.lock` / no pinned versions in `pyproject.toml` (only lower bounds). Risk of upstream breakage.

### 1.4 Build & Test

- **Build:** `hatchling`; `pip install -e .[dev]` works.
- **Linting:** `ruff` (E/W/F/I/B/C4/UP); line-length 100.
- **Type checking:** `mypy` with `disallow_untyped_defs = true`, `ignore_missing_imports = true`.
- **Tests:** 22 unit tests in `tests/unit/`; 0 integration tests.
- **CI:** `.github/workflows/ci.yml` — runs ruff + mypy + pytest on Python 3.11 & 3.12. All pass.
- **Coverage:** Unit tests cover critical safety paths, protocol contracts, hardening behaviour. Sensor integration, scene loading, CV, and streaming audio are untested.

### 1.5 Deploy Assumptions

- Direct Python process (`photonic run`) launched manually on a Linux/macOS host.
- No container, no process manager, no log rotation, no auto-restart.
- Hardware expected on host: USB audio I/F, USB-MIDI (XDJ-AZ), USB-DMX (Enttec) or Art-Net on LAN.
- No secrets or network services exposed except optional Art-Net UDP.

---

## 2. Risk Register

Severity: **C** = Critical (blocks production), **H** = High, **M** = Medium, **L** = Low.

| # | Category | Risk | Severity | Mitigation State |
|---|----------|------|----------|-----------------|
| R1 | **Safety** | Laser Y-axis clamp depends on correct `start_address` in fixture config; misconfigured address silently bypasses hardware safety clamp | C | Partial — dual-layer clamp exists but no config validation at startup |
| R2 | **Safety** | Strobe cooldown logic present (`safety_interlock.py`) but enforcement on DMX channels is stubbed (TODO comment) | H | None — must complete before use with photosensitive hazard |
| R3 | **Safety** | Beat confidence → intensity dimming is a skeleton (TODO in `safety_interlock.py`) — won't reduce light intensity on confidence loss | M | None |
| R4 | **Safety** | Emergency stop (`trigger_emergency_stop()`) is never called programmatically; no automatic trigger on watchdog timeout | M | Watchdog sends blackout packet; stop() is not called until signal |
| R5 | **Reliability** | No startup validation of fixture profiles or scene JSON files — runtime `KeyError`/`FileNotFoundError` in `scene_select.__call__()` | H | None |
| R6 | **Reliability** | Scene library is empty — system falls back to default scene; first run will produce no light output without user authoring JSON | H | None |
| R7 | **Reliability** | MIDI CC map for XDJ-AZ is approximate and unverified against real hardware | H | None — needs hardware test |
| R8 | **Reliability** | CV ROI (bpm_roi, waveform_roi) requires manual pixel coordinates; no calibration guidance or auto-detect | H | None — calibration script missing |
| R9 | **Reliability** | No lock/supervisor file — two `photonic run` processes can race over DMX/USB port | M | OS-level port locking via pyftdi/serial; Art-Net has no guard |
| R10 | **Reliability** | BeatNet backend import tested but real audio path through BeatNet untested in CI | M | Fallback path always works; risk = degraded beat quality |
| R11 | **Performance** | `run_loop` runs LangGraph synchronously; a slow node (e.g. librosa FFT) blocks DMX TX update — only mitigated by the independent DMX TX thread | M | DMX TX thread independent at 40 Hz; analysis may fall behind at high BPM |
| R12 | **Performance** | No frame-rate budget enforcement — graph can run slower than 50 Hz without warning | M | `processing_times` dict populated but never logged or alerted on |
| R13 | **Observability** | No persistent log file or log rotation — `structlog` writes to stdout only | H | None |
| R14 | **Observability** | No metrics/telemetry exporter (Prometheus endpoint promised in old plan; not implemented) | M | `processing_times` collected locally |
| R15 | **Operability** | No systemd/process supervisor — crash = dark stage | H | None |
| R16 | **Operability** | No healthcheck endpoint — cannot externally verify process is alive | M | Heartbeat watchdog is internal-only |
| R17 | **Release safety** | No pinned dependency lockfile — upstream changes can break build between shows | M | None |
| R18 | **Security** | Art-Net UDP target defaults to broadcast (`255.255.255.255`) — DMX frames visible to entire LAN | L | Config option `artnet_target` can be set to unicast |
| R19 | **Security** | No secrets in this codebase; no API keys, no auth surface | N/A | — |
| R20 | **Config** | `pydantic-settings` reads env vars; no env var documentation; operator may unknowingly override safety limits | M | None |

---

## 3. Prioritized Implementation Plan

### Phase 0 — Blockers (required before any live use)
**Target: 1 week. Gate: all acceptance criteria pass.**

#### P0-1: Startup validation (R5, R1)
Add a `validate_graph_config(config)` function called in `build_photonic_graph()` that:
- Checks every `fixture.profile` path exists (YAML file or inline config).
- Checks every scene name referenced in `default_scene` / `pad_overrides` has a corresponding JSON in `config/scenes/`.
- Validates no two fixtures share DMX address ranges (R1 root cause).
- Raises `ConfigError` with a specific message on any violation.

**Files:** `core/config.py`, `graph/builder.py`
**Acceptance:** `photonic run` with a deliberately misconfigured fixture raises `ConfigError` within 1 second; good config proceeds normally.

#### P0-2: Scene library (R6)
Add 6 example scene JSON files to `config/scenes/`:
`intro.json`, `verse.json`, `buildup.json`, `drop.json`, `breakdown.json`, `outro.json`.
Each must exercise all fixture types (laser, moving_head, panel) with different patterns and valid safety limits.

**Files:** `config/scenes/*.json`
**Acceptance:** `photonic run` with `default_scene: intro` runs without `FileNotFoundError`; fixture commands are non-zero.

#### P0-3: Complete strobe cooldown enforcement (R2)
In `safety_interlock.py`, finish the strobe channel enforcement (currently a TODO):
- Track last-strobe-on timestamp per fixture.
- If time-since-last-strobe < `cooldown_s`, set strobe channel to 0 in the DMX universe buffer.
- Log when cooldown is active.

**Files:** `graph/nodes/safety_interlock.py`
**Acceptance:** New test `test_safety_interlock.py::test_strobe_cooldown_blocks_rapid_strobe` — two consecutive strobe-on commands within cooldown window → second command has strobe channel = 0.

#### P0-4: Verify MIDI CC map (R7)
Test `midi_sense.py` CC constants against a real XDJ-AZ (or the official Pioneer DJ MIDI implementation spec PDF):
- Correct `CROSSFADER_CC`, `CHANNEL_FADER_CC`, `FILTER_CC`, `EQ_CC`, `PAD_NOTES` values.
- Document each mapping with source reference in `midi_sense.py`.

**Files:** `graph/nodes/midi_sense.py`
**Acceptance:** Engineer with XDJ-AZ confirms CCs respond correctly by running `photonic run --mock-dmx` and observing log output from `midi_sense`.

---

### Phase 1 — High-impact hardening (recommended before repeated live use)
**Target: 1 week. Gate: CI green + manual tests pass.**

#### P1-1: Persistent structured logs with rotation (R13)
In `ui/cli.py`, configure `structlog` to:
- Write JSON to `$PHOTONIC_LOG_DIR/photonic.jsonl` (default `/var/log/photonic/` or `./logs/`).
- Use `logging.handlers.RotatingFileHandler` (10 MB, 5 backups).
- Keep stderr output for interactive sessions.
- Add `photonic_log_dir` to `AppConfig`.

**Files:** `ui/cli.py`, `core/config.py`
**Acceptance:** `photonic run` for 5 seconds; `./logs/photonic.jsonl` exists; each line is valid JSON; `jq .` parses all lines without error.

#### P1-2: Systemd service unit (R15)
Create `deploy/photonic.service` with:
- `Restart=on-failure`, `RestartSec=5s`.
- `KillMode=mixed` (sends SIGTERM to process group, waits 10s, then SIGKILL).
- `StandardOutput=journal`, `StandardError=journal`.
- `Environment=PHOTONIC_LOG_DIR=/var/log/photonic`.
- `CapabilityBoundingSet=CAP_NET_BIND_SERVICE` only (Art-Net needs no special caps if port ≥ 1024).

**Files:** `deploy/photonic.service` (new), `docs/runbook.md` (new)
**Acceptance:** `systemctl start photonic` → `systemctl status photonic` shows Active; sending SIGTERM → logs show clean shutdown; `systemctl status` shows Inactive (not Failed).

#### P1-3: Frame-rate alerting (R12)
In `graph/builder.py::run_loop`, compute `loop_dt` per iteration and:
- Log `WARN slow_frame loop_dt=X.Xms threshold=25ms` via structlog when `loop_dt > 1.5 * target_dt`.
- Accumulate a `slow_frame_count`; log summary at INFO on shutdown.

**Files:** `graph/builder.py`
**Acceptance:** Introduce an artificial 50ms sleep in a test node; `pytest` captures structlog output and asserts `slow_frame` warning appears.

#### P1-4: CV calibration helper (R8)
Create `scripts/calibrate_cv.py`:
- Captures one screenshot via `mss`.
- Opens an OpenCV window; user clicks top-left and bottom-right of BPM region, then waveform region.
- Prints YAML config snippet: `cv: bpm_roi: [x, y, w, h]  waveform_roi: [x, y, w, h]`.
- Optionally auto-detects HSV color thresholds by sampling live waveform.

**Files:** `scripts/calibrate_cv.py` (new)
**Acceptance:** Operator runs `python scripts/calibrate_cv.py`; output pasted into `config/default.yaml`; `photonic run` shows non-zero `cv_bpm` within 5 seconds.

#### P1-5: Dependency lockfile (R17)
Generate `requirements.lock` via `pip-compile` (or `uv pip compile`) from `pyproject.toml`:
```bash
pip-compile pyproject.toml --output-file requirements.lock --extra dev
```
Pin to exact versions for production deployments. Add lockfile to `.gitignore` so dev environments get fresh resolves; document that production deploys must use the lockfile.

**Files:** `requirements.lock` (new), `deploy/README.md` or `docs/runbook.md`
**Acceptance:** `pip install --require-hashes -r requirements.lock` succeeds in a fresh venv.

#### P1-6: Art-Net unicast default (R18)
Change default `artnet_target` in `config/default.yaml` from broadcast (`255.255.255.255`) to `127.0.0.1` (loopback as safe default). Document that operators must set it to the actual Art-Net controller IP.

**Files:** `config/default.yaml`, `docs/runbook.md`
**Acceptance:** `grep artnet_target config/default.yaml` shows unicast. Manual Art-Net test to correct controller IP succeeds.

---

### Phase 2 — Observability & resilience (strongly recommended)
**Target: 1–2 weeks.**

#### P2-1: Processing-time metrics export
Expose a `/metrics` HTTP endpoint (Prometheus text format) on localhost:9090 using stdlib `http.server` in a daemon thread:
- `photonic_loop_dt_seconds` histogram
- `photonic_slow_frames_total` counter
- `photonic_dmx_tx_errors_total` counter
- `photonic_beat_confidence` gauge
- `photonic_safety_interlocks_total` counter

**Files:** `core/metrics.py` (new), `graph/builder.py`, `ui/cli.py`
**Acceptance:** `curl -s http://localhost:9090/metrics | grep photonic_loop_dt` returns histogram lines.

#### P2-2: Test coverage to ≥ 70%
Add unit tests for:
- `audio_sense.py` — ring buffer fills; overflow counter increments.
- `feature_extract.py` — dummy-feature path when librosa absent.
- `beat_track.py` — RMS fallback fires when no backend; bar position increments.
- `scene_select.py` — JSON scene loading; fallback to default scene on missing file.
- `builder.py` — `build_minimal_graph()` runs one step without hardware.
- `safety_interlock.py` — complete strobe cooldown test (from P0-3).

**Files:** `tests/unit/test_audio_sense.py`, `test_beat_track.py`, `test_scene_select.py`, `test_builder.py`
**Acceptance:** `pytest --cov=src/photonic_synesthesia --cov-report=term-missing` reports ≥ 70% total; CI gate added.

#### P2-3: Lock/PID file (R9)
In `cli.py::run`, write a PID file to `/tmp/photonic.pid` on start; remove it on clean shutdown. On startup, check if file exists and process is alive; if so, refuse to start with clear error.

**Files:** `ui/cli.py`
**Acceptance:** Two concurrent `photonic run` invocations → second exits with "already running (PID XXX)".

#### P2-4: Beat-confidence dimming (R3)
In `safety_interlock.py::__call__`, implement the stubbed beat-confidence block:
- If `state['beat_confidence'] < config.safety.min_beat_confidence` (default 0.3):
  - Scale all dimmer channels (those marked `type: dimmer` in fixture profile, or positions 0 in absence of profile) by `beat_confidence / min_beat_confidence`.
  - Log `WARN reduced_intensity_low_confidence` once per 5 seconds.

**Files:** `graph/nodes/safety_interlock.py`
**Acceptance:** New test: set `beat_confidence=0.1`; assert at least one dimmer channel in fixture commands is scaled < 100%.

---

### Phase 3 — Completeness & operations (nice-to-have)
**Target: ongoing.**

| Item | Action | File(s) |
|------|--------|---------|
| Fixture profile YAML loader | Load channel maps from `config/fixtures/*.yaml` instead of hardcoding in nodes | `graph/nodes/fixture_control.py`, `core/config.py` |
| Web panel | Implement FastAPI + WebSocket serving real-time state JSON | `ui/web_panel.py` |
| Scene hot-reload | Add `photonic reload` CLI command; re-reads `config/scenes/*.json` without restart | `ui/cli.py`, `graph/nodes/scene_select.py` |
| CV color threshold calibration | Move HSV ranges from hardcoded to `config/default.yaml` `cv.color_thresholds` | `graph/nodes/cv_sense.py`, `config/default.yaml` |
| Optional Sentry integration | `PHOTONIC_SENTRY_DSN` env var → sentry-sdk init; capture unhandled exceptions | `core/exceptions.py` |
| Production runbook | Document: startup checklist, signal handling, watchdog, DMX test flow, emergency stop | `docs/runbook.md` |

---

## 4. Validation Commands

Run these in order to validate each phase.

### Pre-flight (always)
```bash
# Install with dev extras
pip install -e ".[dev]"

# Lint (must be 0 errors)
ruff check src/ tests/

# Type check (must be 0 errors)
mypy src/

# Unit tests with coverage
pytest tests/unit/ -v --tb=short --cov=src/photonic_synesthesia --cov-report=term-missing

# Confirm CI parity (same matrix as .github/workflows/ci.yml)
tox -e py311,py312   # if tox configured, else run manually
```

### Phase 0 — Config safety
```bash
# Trigger startup validation with bad fixture config (should exit 1 with ConfigError)
photonic run --config tests/fixtures/bad_fixture_overlap.yaml 2>&1 | grep "ConfigError"

# Trigger missing scene (should exit 1 with ConfigError)
photonic run --config tests/fixtures/missing_scene.yaml 2>&1 | grep "ConfigError"

# Confirm strobe cooldown blocks (unit test)
pytest tests/unit/test_safety_interlock.py::test_strobe_cooldown_blocks_rapid_strobe -v
```

### Phase 1 — Logging & process management
```bash
# Structured JSON log output
photonic run --config config/default.yaml &
sleep 5 && kill -TERM $!
jq . ./logs/photonic.jsonl | head -20

# Verify SIGTERM causes clean shutdown (no hung threads)
photonic run --mock-all &
sleep 3 && kill -TERM $!
# Should exit 0; no "Exception in thread" messages

# systemd smoke test (requires deploy/photonic.service installed)
sudo systemctl start photonic
sudo systemctl status photonic | grep Active
sudo systemctl stop photonic
sudo systemctl status photonic | grep -v failed

# DMX hardware test (real hardware)
photonic dmx-test --channel 1 --value 255
# Verify fixture ch1 is at full brightness; CTRL-C → blackout sent
```

### Phase 1 — Art-Net
```bash
# Verify Art-Net packet on LAN (tcpdump/wireshark)
tcpdump -i any udp port 6454 -X -c 5

# Verify unicast default (no broadcast)
grep artnet_target config/default.yaml | grep -v "255.255.255.255"
```

### Phase 2 — Metrics & coverage
```bash
# Coverage gate
pytest --cov=src/photonic_synesthesia --cov-fail-under=70

# Metrics endpoint
photonic run --config config/default.yaml &
sleep 2
curl -s http://localhost:9090/metrics | grep photonic_loop_dt
kill -TERM $!

# PID file guard
photonic run &
sleep 1
photonic run  # Should print error and exit 1
kill -TERM $!
```

### Phase 2 — Beat confidence safety
```bash
pytest tests/unit/test_safety_interlock.py::test_beat_confidence_dims_output -v
```

### End-to-end mock run (no hardware required)
```bash
# Full graph with all sensors mocked
photonic run --mock-audio --mock-midi --mock-cv --mock-dmx --duration 10

# Expected: no exceptions; log shows beat_confidence, scene transitions, DMX TX cycles
# Coverage: manually confirm log lines for each graph node
```

### Hardware integration checklist (live show)
```bash
# 1. List audio interfaces
photonic list-audio

# 2. List MIDI ports
photonic list-midi

# 3. Test DMX output channel-by-channel
photonic dmx-test --channel 1 --value 255   # Laser mode/dimmer
photonic dmx-test --channel 5 --value 50    # Laser Y-axis (should not exceed safety_max)

# 4. Verify laser Y-axis clamp: value > y_axis_max should be clamped
photonic dmx-test --channel 5 --value 200   # Expect actual output <= 100

# 5. Audio analysis sanity check
photonic analyze --duration 10              # Should show non-zero BPM and beat_confidence

# 6. Run heartbeat test: kill analysis thread and verify blackout within 1s
# (requires debug mode or direct test harness)
```

---

## 5. Blockers & Unknowns

### Hard Blockers (cannot deploy without resolving)

| # | Blocker | Owner | How to Resolve |
|---|---------|-------|----------------|
| B1 | **MIDI CC map unverified** — crossfader, fader, filter, EQ, pad note numbers in `midi_sense.py` are approximate. Wrong CCs = DJ intent completely silent. | Hardware engineer | Boot XDJ-AZ in MIDI mode; use `mido` port monitor (`mido.open_input(..., callback=print)`) to capture real CC values; update constants. |
| B2 | **No built-in scenes** — `config/scenes/` empty. System falls back to "default" scene which may also be absent. First run produces no fixture output. | Show designer | Author minimum 4 scenes (intro, buildup, drop, breakdown) as JSON; validate against `PhotonicState` keys. |
| B3 | **CV ROI requires manual setup** — system does not know the pixel position of the BPM display or waveform on the user's screen. CV-derived BPM is always 0 until calibrated. | Operator | Run `scripts/calibrate_cv.py` (P1-4) before first show; paste output into `config/default.yaml`. If calibration script not yet built: set `cv.enabled: false` and rely on audio BPM only. |

### Soft Blockers (degrade quality if unresolved)

| # | Issue | Impact | Workaround |
|---|-------|--------|------------|
| S1 | Strobe cooldown incomplete (R2) | Strobe rate not enforced between bursts → photosensitivity risk | Disable strobe in scene JSON until P0-3 complete |
| S2 | Beat confidence dimming stubbed (R3) | No automatic intensity reduction on beat loss | Manual `--mock-audio` mode preserves last known beat; acceptable for short gaps |
| S3 | Fixture profile hardcoded | Channel layout errors if fixtures differ from 7-ch laser / 16-ch MH / 6-ch panel assumption | Confirm physical fixtures match assumed profiles; defer profile loader to Phase 3 |
| S4 | BeatNet backend untested | May produce incorrect tempo estimates on some audio | Fall back to madmom; madmom fallback tested and reliable |
| S5 | No process supervisor | Crash = dark stage, no auto-restart | Manual restart procedure; mitigated by systemd in Phase 1 |

### Unknowns

| # | Unknown | Risk Level | Investigation Path |
|---|---------|------------|-------------------|
| U1 | Does pyftdi work reliably with Enttec Open DMX USB on Linux kernel 6.18+? | H | Test `photonic dmx-test` on target host; check dmesg for FTDI driver messages |
| U2 | Does the LangGraph synchronous step-loop maintain < 100ms latency end-to-end on target hardware (4-core, 8GB)? | M | Profile one step with `cProfile`; measure `processing_times` on target machine |
| U3 | Does madmom work on Python 3.14 (test env)? madmom has Cython extensions that may not have 3.14 wheels. | M | `pip install madmom` on Python 3.14 target; if fails, BeatNet or RMS fallback is the only option |
| U4 | XDJ-AZ MIDI channel: does it transmit on channel 1 (default in `midi_sense.py`) or a different channel? | M | Confirmed by hardware test (B1) |
| U5 | Does Art-Net work with the target DMX-over-IP controller, or is FTDI serial the only viable interface? | L | Both implemented; try Art-Net first as it avoids USB driver complexity |

---

## Appendix: Env Variable Reference

All settings come from `core/config.py` (Pydantic BaseSettings). Any key can be overridden via env var with prefix `PHOTONIC_`. Safety-critical env vars:

| Env Var | Default | Description |
|---------|---------|-------------|
| `PHOTONIC_SAFETY__LASER__Y_AXIS_MAX` | 100 | Max DMX value for laser Y-axis (0–255) |
| `PHOTONIC_SAFETY__LASER__MIN_SCAN_SPEED` | 30 | Min scan speed (prevents static beam) |
| `PHOTONIC_SAFETY__STROBE__MAX_RATE_HZ` | 10 | Max strobe frequency |
| `PHOTONIC_SAFETY__SYSTEM__HEARTBEAT_TIMEOUT_S` | 1.0 | Watchdog timeout before blackout |
| `PHOTONIC_DMX__ARTNET_TARGET` | `127.0.0.1` | Art-Net target IP (set to controller IP) |
| `PHOTONIC_LOG_DIR` | `./logs` | Directory for photonic.jsonl output |
| `PHOTONIC_SENTRY_DSN` | (empty) | Sentry DSN for error reporting |

> **Ops note:** Never set `PHOTONIC_SAFETY__*` values without hardware-verified limits for the specific laser fixtures in use. Default values assume a generic 7-channel entertainment laser.
