# Full Code Audit Plan — `laser_show_xdj_az` (photonic-synesthesia)

**Auditor toolkit:** `/home/antoniofortes/Projects/code_auditor` (`codeauditor` CLI)
**Target:** `/home/antoniofortes/Projects/laser_show_xdj_az`
**Scope:** Full repository — safety, correctness, reliability, performance, maintainability, test quality, supply-chain.
**Constraint:** Read-only during audit. No code changes until findings are reviewed.

---

## Deliverable 1 — Step-by-Step Execution Plan

### Phase 0 — Pre-flight Setup (one-time, ~5 min)

**Goal:** Verify both environments are usable and tools are on PATH.

```bash
# 0a. Install code_auditor toolkit (if not already installed)
cd /home/antoniofortes/Projects/code_auditor
pip install -e ".[dev]"

# 0b. Verify tool availability
codeauditor toolchain --require pytest,mypy,ruff,bandit,vulture,radon --enforce

# 0c. Install target project in editable mode (needed for mypy / pytest)
cd /home/antoniofortes/Projects/laser_show_xdj_az
pip install -e ".[dev]"

# 0d. Confirm test suite is runnable (baseline)
pytest tests/ -q --tb=short 2>&1 | tail -20
```

**Expected artifacts:** Tool availability table printed to console; no crashes.

---

### Phase 1 — Automated Multi-Phase Audit (primary pass, ~5–15 min)

**Goal:** Collect all automated findings across all 9 phases with a single command.

```bash
cd /home/antoniofortes/Projects/laser_show_xdj_az

# Full audit, SARIF output for IDE integration
codeauditor audit \
  --project . \
  --sarif-out data/audit/photonic_audit.sarif \
  --enforce

# Output lands in data/code_auditor/ by default
```

**Phases executed:** preflight → toolchain → patterns → lint → types → tests → security → dead-code → complexity

**Expected artifacts:**
| File | Contents |
|------|----------|
| `data/code_auditor/summary.{json,md}` | Aggregate counts by severity, ci_pass flag |
| `data/code_auditor/phases/lint_report.{json,md}` | Ruff findings (LINT-*) |
| `data/code_auditor/phases/types_report.{json,md}` | Mypy type errors (TYPE-*) |
| `data/code_auditor/phases/tests_report.{json,md}` | Pytest pass/fail (TEST-*) |
| `data/code_auditor/phases/security_report.{json,md}` | Bandit security issues (SEC-*) |
| `data/code_auditor/phases/dead-code_report.{json,md}` | Vulture unused symbols (DEAD-*) |
| `data/code_auditor/phases/complexity_report.{json,md}` | Radon CC grades (CC-*) |
| `data/code_auditor/evidence.jsonl` | Subprocess audit trail |
| `data/audit/photonic_audit.sarif` | Merged SARIF for IDE / PR comments |

> **Note:** Preflight will produce MEDIUM findings for missing `scripts/check_patterns.py`,
> `best_practices/patterns.json`, etc. — these are expected since the project does not use
> code_auditor's scaffolding natively. Record but do not block on PRE-* findings.

---

### Phase 2 — Quick Focused Re-runs (targeted passes, ~10 min)

Run individual tools directly for maximum control over paths and flags:

```bash
cd /home/antoniofortes/Projects/laser_show_xdj_az

# 2a. Lint with full rule set (ruff)
ruff check src/ tests/ --select=ALL --output-format=full 2>&1 | tee data/audit/ruff_full.txt

# 2b. Type check with strict flags (mypy)
mypy src/photonic_synesthesia \
  --strict \
  --ignore-missing-imports \
  --no-incremental \
  2>&1 | tee data/audit/mypy_strict.txt

# 2c. Security scan (bandit) — include low-severity, full detail
bandit -r src/ -f json -l -i -o data/audit/bandit_full.json

# 2d. Dead code with lower confidence threshold
vulture src/ tests/ --min-confidence 60 2>&1 | tee data/audit/vulture_60.txt

# 2e. Complexity — show per-function CC grades
radon cc src/ -s -a -n C 2>&1 | tee data/audit/radon_cc.txt

# 2f. Maintainability index
radon mi src/ -s 2>&1 | tee data/audit/radon_mi.txt
```

**Expected artifacts:** Raw tool output in `data/audit/` for manual triage.

---

### Phase 3 — Manual Deep Dive (priority surfaces)

Focus manual review on files where automated tools have limited coverage.
See Deliverable 3 for priority order.

**3a. Safety-Critical Code Review**
Read and annotate each file against the IMPLEMENTATION_PLAN.md spec:
- `src/photonic_synesthesia/graph/nodes/safety_interlock.py`
- `src/photonic_synesthesia/interpreters/safety.py`
- `src/photonic_synesthesia/graph/nodes/dmx_output.py`
- `src/photonic_synesthesia/dmx/artnet.py`

Checklist per file:
- [ ] Does every unsafe hardware write go through a safety check first?
- [ ] Are numeric bounds (laser Y-axis, strobe Hz) enforced with `>=` not `>`?
- [ ] Is there a fallback path when the heartbeat times out?
- [ ] Can an exception in the node silently skip the safety interlock?

**3b. Concurrency Review**
Files: `graph/nodes/audio_sense.py`, `midi_sense.py`, `dmx_output.py`, `graph/builder.py`

Checklist:
- [ ] All shared mutable state behind a lock?
- [ ] Ring buffers accessed from both callback thread and main thread — synchronized?
- [ ] MIDI callback thread — can it raise into the main thread?
- [ ] `PhotonicGraph.run_loop()` — what happens if a node raises?
- [ ] `threading.Event` vs `threading.Lock` usage consistent?

**3c. Config / Input Validation**
Files: `core/config.py`, `config/default.yaml`

Checklist:
- [ ] All numeric safety bounds have `ge=` / `le=` Pydantic validators?
- [ ] `artnet_host` validated as IPv4 (not shell-injectable)?
- [ ] `midi.port_name` — any path traversal risk if set from env?
- [ ] `pyftdi` URL (`ftdi://...`) — injection possible from config?

**3d. LangGraph State Integrity**
Files: `core/state.py`, `graph/builder.py`, `graph/nodes/fusion.py`

Checklist:
- [ ] `PhotonicState` TypedDict — all keys initialized in `create_initial_state()`?
- [ ] Any node writing to state keys that another node reads assumes present — missing key = KeyError?
- [ ] Conditional edges in builder — do all branches lead to `dmx_output` or `safety_interlock`?
- [ ] `StateHistory` ring buffer — thread-safe (accessed from LangGraph tick and diagnostics)?

**3e. DMX / Art-Net Protocol Correctness**
Files: `dmx/artnet.py`, `graph/nodes/dmx_output.py`

Checklist:
- [ ] Art-Net packet header (`Art-Net\0`, OpCode 0x5000) correct per spec?
- [ ] Universe encoding big-endian vs little-endian (Art-Net is little-endian)?
- [ ] Channel count always 512 or padded to even?
- [ ] Socket reuse / cleanup on error?

---

### Phase 4 — Dependency & Supply-Chain Review (~20 min)

```bash
cd /home/antoniofortes/Projects/laser_show_xdj_az

# 4a. Check for known CVEs in pinned deps
pip-audit --require-hashes 2>&1 | tee data/audit/pip_audit.txt
# or if pip-audit not available:
safety check 2>&1 | tee data/audit/safety.txt

# 4b. Inspect dependency tree for unexpected transitive deps
pip list --format=columns 2>&1 | tee data/audit/pip_list.txt
pipdeptree 2>&1 | tee data/audit/pipdeptree.txt

# 4c. Flag unpinned deps (no version pin = supply-chain risk)
grep -E '^\s*"[a-z]' pyproject.toml | grep -v '>=' | grep -v '==' | tee data/audit/unpinned.txt
```

**Key packages to scrutinize:**
| Package | Risk |
|---------|------|
| `madmom>=0.16.1` | Last release 2017; NumPy 2.x compat unknown; no upper bound |
| `BeatNet>=1.1.1` (optional) | Small library; provenance unclear |
| `langgraph>=0.2.0` | Rapidly evolving; wide version range |
| `pyftdi>=0.55.0` | Hardware USB driver; privilege implications |
| `essentia>=2.1b6` (optional ml) | Beta release, large binary |

---

### Phase 5 — Test Quality Assessment (~10 min)

```bash
# 5a. Coverage report
pytest tests/ \
  --cov=src/photonic_synesthesia \
  --cov-report=term-missing \
  --cov-report=html:data/audit/htmlcov \
  -q 2>&1 | tee data/audit/pytest_coverage.txt

# 5b. Mutation test (optional, slow — run on safety modules only)
mutmut run \
  --paths-to-mutate src/photonic_synesthesia/interpreters/ \
  --runner "pytest tests/unit/test_interpreter_node.py" \
  2>&1 | tee data/audit/mutmut.txt
```

**Baseline expectation:** Coverage is expected to be very low (3 test files, ~12 tests covering ~5% of the codebase). Document gap vs safety-critical paths.

---

## Deliverable 2 — Risk Taxonomy

### R1 · Safety / Physical Harm (CRITICAL tier)
Laser and strobe failures can cause eye damage or photosensitive seizures.

| Risk ID | Description | Files |
|---------|-------------|-------|
| S-1 | Safety interlock bypassable via exception in upstream node | `safety_interlock.py`, `builder.py` |
| S-2 | Strobe Hz cap not enforced if `DirectorEngine` returns out-of-bounds value | `director/engine.py`, `safety.py` |
| S-3 | Laser Y-axis hard clamp may not apply to all fixture types | `fixture_control.py`, `safety_interlock.py` |
| S-4 | Heartbeat timeout: blackout logic not tested | `safety_interlock.py`, tests (absent) |
| S-5 | Emergency stop state not persisted across graph restart | `state.py` |

### R2 · Correctness (HIGH tier)
Real-time system; wrong output = hardware damage or show failure.

| Risk ID | Description | Files |
|---------|-------------|-------|
| C-1 | Art-Net universe byte order wrong (should be LE per spec) | `dmx/artnet.py` |
| C-2 | Missing keys in `PhotonicState` TypedDict cause silent `KeyError` | `core/state.py` |
| C-3 | BPM fusion uses unpinned float comparison; NaN propagation | `graph/nodes/fusion.py` |
| C-4 | `madmom` ring buffer race between audio callback and analysis | `audio_sense.py` |
| C-5 | Off-by-one in delta limiting allows `max_delta+1` steps | `interpreters/safety.py` |

### R3 · Reliability (HIGH tier)
50 Hz real-time loop; latency spikes or crashes drop frames.

| Risk ID | Description | Files |
|---------|-------------|-------|
| RL-1 | Unhandled exception in any LangGraph node terminates loop silently | `builder.py` |
| RL-2 | librosa operations GIL-bound; can cause >20ms latency spike | `feature_extract.py` |
| RL-3 | `mss` screen-capture blocks main thread; no timeout | `cv_sense.py` |
| RL-4 | UDP socket not recreated after network error | `dmx/artnet.py` |
| RL-5 | No backpressure on audio ring buffer; dropped frames undetected | `audio_sense.py` |

### R4 · Performance (MEDIUM tier)

| Risk ID | Description | Files |
|---------|-------------|-------|
| P-1 | `librosa.feature.*` called per-frame (not streaming) | `feature_extract.py` |
| P-2 | OpenCV template matching with no ROI — full-screen every tick | `cv_sense.py` |
| P-3 | `StateHistory` ring buffer copies full state dict each tick | `core/state.py` |
| P-4 | High CC complexity in `scene_select.py` / `director/engine.py` | `director/engine.py` |

### R5 · Maintainability (MEDIUM tier)

| Risk ID | Description | Files |
|---------|-------------|-------|
| M-1 | Fixture profile YAML stubs are empty — no validation path | `config/fixtures/` |
| M-2 | Scene JSON stubs empty — `scene_select.py` untested | `config/scenes/` |
| M-3 | No CI/CD pipeline — no automated gate before merge | repo root |
| M-4 | Magic numbers (250000 baud, 0x5000, 6454) not named constants | `dmx/artnet.py`, `dmx_output.py` |
| M-5 | `mocks.py` shares implementation logic instead of pure stubs | `graph/nodes/mocks.py` |

### R6 · Test Quality (HIGH tier, given safety-critical context)

| Risk ID | Description | Files |
|---------|-------------|-------|
| T-1 | No tests for `safety_interlock.py` (most critical node) | `tests/unit/` |
| T-2 | No concurrency tests (race conditions cannot be caught statically) | `tests/` |
| T-3 | No integration tests covering full graph tick | `tests/integration/` |
| T-4 | `test_artnet.py` doesn't validate byte-level packet layout against spec | `tests/unit/test_artnet.py` |
| T-5 | No property-based testing on safety-constraint functions | `tests/unit/test_interpreter_node.py` |

### R7 · Dependency / Supply-Chain (MEDIUM tier)

| Risk ID | Description | Files |
|---------|-------------|-------|
| D-1 | `madmom` abandoned (last release 2017) | `pyproject.toml` |
| D-2 | All deps use `>=` with no upper bound — breaking change risk | `pyproject.toml` |
| D-3 | No lockfile (`requirements.lock`, `uv.lock`) — non-reproducible builds | repo root |
| D-4 | `BeatNet` and `essentia` are optional extras with no CVE tracking | `pyproject.toml` |
| D-5 | `pyftdi` (hardware USB) requires elevated USB permissions — not documented | README |

---

## Deliverable 3 — Prioritized Review Surface

Priority order based on blast radius × probability × safety impact:

| Priority | Path | Why |
|----------|------|-----|
| **P0 — Safety-critical** | `graph/nodes/safety_interlock.py` | Last line of defense before hardware; zero tests |
| **P0 — Safety-critical** | `interpreters/safety.py` | Implements all channel clamps; used every frame |
| **P0 — Safety-critical** | `graph/nodes/dmx_output.py` | Writes raw bytes to hardware; timing-critical |
| **P1 — Protocol correctness** | `dmx/artnet.py` | Art-Net packet layout; byte-order bugs are silent |
| **P1 — Concurrency** | `graph/nodes/audio_sense.py` | Ring buffer shared between threads |
| **P1 — Concurrency** | `graph/builder.py` | Exception propagation from nodes; run_loop design |
| **P2 — Config/validation** | `core/config.py` | Safety bounds must have Pydantic validators |
| **P2 — Core state** | `core/state.py` | TypedDict completeness; missing key = runtime crash |
| **P2 — AI logic** | `director/engine.py` | Strobe budget enforcement; ML override path |
| **P3 — Sensor inputs** | `graph/nodes/fusion.py` | NaN propagation; BPM consensus logic |
| **P3 — Sensor inputs** | `graph/nodes/beat_track.py` | madmom thread safety |
| **P3 — Sensor inputs** | `graph/nodes/cv_sense.py` | Blocking mss call; OCR accuracy |
| **P4 — Tests** | `tests/unit/test_artnet.py` | Byte-level layout coverage |
| **P4 — Tests** | `tests/unit/test_interpreter_node.py` | Boundary value coverage |
| **P4 — Tests** | `tests/unit/test_director_engine.py` | ML override path coverage |
| **P5 — Dependencies** | `pyproject.toml` | CVE check; upper-bound pins |

---

## Deliverable 4 — Validation Strategy (avoiding false positives)

### Automated finding triage rules

1. **PRE-* (preflight):** Suppress all — the project doesn't use code_auditor scaffolding.
2. **TOOL-* (toolchain):** Accept as-is.
3. **LINT-* (ruff):** Accept `F` (pyflakes) and `B` (bugbear) codes as real. Review `E/W` in context.
4. **TYPE-* (mypy):** Accept all `error:` lines. Ignore `note:` lines as informational.
5. **SEC-* (bandit):** Accept `HIGH` confidence findings unconditionally. For `MEDIUM`, verify:
   - UDP socket: flag if `SO_BROADCAST` is enabled without documentation of intent.
   - `assert` statements used for safety checks: flag as real (bandit B101 correct).
   - Hardcoded IP `255.255.255.255`: flag as MEDIUM (documented, not critical).
6. **DEAD-* (vulture):** Treat any dead code in `safety_interlock.py` or `interpreters/safety.py` as HIGH (dead safety code = unreachable path).
7. **CC-* (radon):** Focus on grade D or F functions (CC > 10). Grade C (CC 6-10) in safety nodes = flag.
8. **ROUTE-*:** Skip entirely — no FastAPI routes in this project.

### Cross-validation steps

```bash
# For any SEC-* finding, confirm line + context:
grep -n "assert\|SO_BROADCAST\|shell=True" src/photonic_synesthesia/**/*.py

# For any TYPE-* finding in safety nodes, confirm Pydantic validators present:
grep -n "ge=\|le=\|gt=\|lt=\|validator" src/photonic_synesthesia/core/config.py

# For any DEAD-* finding in safety paths, confirm it is truly unreachable:
grep -rn "safety_interlock\|SafetyConstraint" src/ tests/
```

### Manual verification protocol for safety findings

For each R1/R2 risk identified, apply the "two-path test":
1. **Happy path:** Trace from `create_initial_state()` through every graph node to `ArtNetTransmitter.send()`. Confirm safety checks run.
2. **Failure path:** Introduce a hypothetical exception in each upstream node. Confirm `safety_interlock.py` still executes (or that the exception causes a blackout, not a freeze).

---

## Deliverable 5 — Post-Audit Outputs

### Report structure

```
data/audit/
├── AUDIT_REPORT.md           # Executive summary (this template)
├── findings/
│   ├── S_safety.md           # R1 safety findings — Critical/High
│   ├── C_correctness.md      # R2 correctness findings — High
│   ├── RL_reliability.md     # R3 reliability findings — High/Medium
│   ├── P_performance.md      # R4 performance findings — Medium
│   ├── M_maintainability.md  # R5 maintainability findings — Medium/Low
│   ├── T_test_quality.md     # R6 test findings — High (given safety context)
│   └── D_deps.md             # R7 supply-chain findings — Medium/Low
├── photonic_audit.sarif      # Machine-readable SARIF 2.1.0
├── summary.json              # codeauditor summary
├── phases/                   # Per-phase JSON + MD reports
├── ruff_full.txt
├── mypy_strict.txt
├── bandit_full.json
├── vulture_60.txt
├── radon_cc.txt
├── radon_mi.txt
├── pytest_coverage.txt
├── pip_audit.txt
└── pipdeptree.txt
```

### Severity rubric

| Severity | Criteria | Required action |
|----------|----------|-----------------|
| **CRITICAL** | Laser/strobe safety interlock can be bypassed; protocol exploit | Fix before any live use |
| **HIGH** | Uncaught exception crashes the loop; race condition in shared state; CVE in dep | Fix before beta |
| **MEDIUM** | Missing validator on safety config field; dead code in safety path; no lockfile | Fix before first real performance |
| **LOW** | Style/lint violation; unused import; dead code outside safety paths | Fix in backlog sprint |
| **INFO** | Design suggestion; refactor opportunity; documentation gap | Optional / no deadline |

### `AUDIT_REPORT.md` executive section template

```markdown
# Photonic Synesthesia — Audit Report
**Date:** YYYY-MM-DD
**Auditor:** [name / tool]
**Version audited:** git SHA

## Risk Scorecard
| Category | Critical | High | Medium | Low |
|----------|----------|------|--------|-----|
| Safety   |          |      |        |     |
| Correctness |       |      |        |     |
| Reliability |       |      |        |     |
| Test Quality |      |      |        |     |
| ...      |          |      |        |     |
| **Total** |         |      |        |     |

## CI-pass: YES / NO (block if Critical or High present)

## Top 5 Findings (must fix before live deployment)
1. ...

## Recommended fix order
Phase A (before any live use): All Critical + Safety High findings
Phase B (before first performance): Remaining High findings
Phase C (backlog): Medium + Low findings
```

---

## Execution Checklist

- [ ] Phase 0: Environment & toolchain ready
- [ ] Phase 1: `codeauditor audit` complete — summary.md reviewed
- [ ] Phase 2: Individual tool passes complete — raw outputs in `data/audit/`
- [ ] Phase 3a: Safety-critical manual review complete
- [ ] Phase 3b: Concurrency manual review complete
- [ ] Phase 3c: Config validation review complete
- [ ] Phase 3d: LangGraph state integrity review complete
- [ ] Phase 3e: DMX/Art-Net protocol review complete
- [ ] Phase 4: Dependency CVE scan complete
- [ ] Phase 5: Coverage report + mutation test (safety modules) complete
- [ ] All findings triaged and false positives suppressed
- [ ] `AUDIT_REPORT.md` drafted with risk scorecard
- [ ] Findings prioritized by severity rubric
- [ ] Fix roadmap (Phase A/B/C) agreed with maintainer
