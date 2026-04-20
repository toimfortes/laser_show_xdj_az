# 2026-04-20 Run-File Destructive Review (Cycle 3)

## Scope

Fresh destructive review of the `photonic run-file ... --web --ilda-transport memory` failure path using the current worktree on 2026-04-20. This review does **not** trust earlier conclusions without re-verification.

Primary questions:

1. Is the bare `photonic` command running the wrong interpreter?
2. Are the uncommitted `feature_extract.py` edits the root cause?
3. Does the `run-file` runtime fail because of the button workflow, or does it already fail before any UI interaction?
4. What is the first-principles reason the terminal appears hung and playback stalls?

## Evidence Collected

### Interpreter resolution

- `which photonic` -> `/home/antoniofortes/.local/bin/photonic`
- Shebang -> `#!/usr/bin/python3`
- `/usr/bin/python3 --version` -> `Python 3.14.3`
- `./.venv/bin/python --version` -> `Python 3.12.13`
- Both installs are editable against the same repo:
  - user install: `/home/antoniofortes/.local/lib/python3.14/site-packages`
  - repo venv: `/home/antoniofortes/Projects/laser_show_xdj_az/.venv/lib64/python3.12/site-packages`
  - editable project location: `/home/antoniofortes/Projects/laser_show_xdj_az`

### Direct extractor reproduction

Using the same MP3 and the current repo code, `_extract_features()` completed successfully under both:

- Python `3.12.13`
- Python `3.14.3`

This directly disproves the claim that the current `feature_extract.py` worktree necessarily throws `'float' object is not callable'` on Python 3.14.

### Full `run-file` reproduction

Command used:

```bash
PYTHONFAULTHANDLER=1 timeout -k 5s 35s photonic run-file \
  "/run/media/antoniofortes/C2F7-FA12/Contents/Agents of Time/Zodiac/Agents of Time - Zodiac_pn.mp3" \
  --web --web-port 8876 --ilda-transport memory
```

Observed behavior:

- No segfault reproduced.
- No `'float' object is not callable'` reproduced.
- Repeated safety warnings reproduced:
  - `Safety monitor detected stalled output`
  - `Output(s) stalled - triggering emergency blackout`
- After about 35 seconds of wall time, playhead advanced only `1.4s`.

This means the system is already failing badly in the steady-state `run-file` loop before any web UI interaction is required.

### Graph-step profiling

Profiling `graph.step()` directly with file playback showed:

- frame budget at `50 FPS` = `0.020s`
- measured step cost after feature extraction starts:
  - `0.094s`
  - `0.116s`
  - `0.136s`
  - `0.191s`
  - `0.249s`
  - `0.293s`

The dominant node was consistently `feature_extract`.

### Microprofile of the extractor hot path on a 2.0s buffer

Measured on Python `3.14.3`, librosa `0.11.0`, numpy `2.4.4`:

- `pyin`: `0.4800s`
- `hpss_spectrum`: `0.2694s`
- `effects.harmonic`: `0.1183s`
- `chroma_cqt`: `0.0340s`
- `tonnetz`: `0.0313s`
- total measured extractor work: about `0.9681s`

The heavy cost is intrinsic to the current algorithm, not to the UI.

### Worktree vs HEAD benchmark

Benchmarking `HEAD` against the current uncommitted `feature_extract.py` on the same audio buffers:

- `n=2048` samples: `HEAD 0.1069s`, `WORKTREE 0.1006s`
- `n=48000` samples: `HEAD 0.5606s`, `WORKTREE 0.5772s`
- `n=96000` samples: `HEAD 1.1054s`, `WORKTREE 1.0442s`

Result:

- same order of magnitude
- no evidence that the worktree diff created the runtime slowdown
- the worktree actually improves short-window behavior:
  - `HEAD` at `n=960` failed with `ParameterError: Audio buffer is not finite everywhere`
  - `WORKTREE` at `n=960` succeeded

## Findings

### 1. High: `run-file` is fundamentally over budget before any button press

`run-file` feeds `960` samples per tick at 48 kHz for `50 FPS`, which is `20ms` of audio per graph step. The file sensor also grows a rolling buffer up to `2.0s`, and the feature extractor recomputes expensive DSP across the full rolling buffer every tick.

Relevant code:

- `buffer_seconds = 2.0`: [config.py](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/core/config.py:25)
- rolling buffer growth: [audio_file_sense.py](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/graph/nodes/audio_file_sense.py:40), [audio_file_sense.py](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/graph/nodes/audio_file_sense.py:123)
- chunk size derived from FPS: [cli.py](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/ui/cli.py:1499)
- sequential pipeline runs `feature_extract` every tick near the front of the graph: [builder.py](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/graph/builder.py:379)
- graph loop blocks on `graph.step()` synchronously: [cli.py](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/ui/cli.py:1730)

This is the primary root cause of the apparent hang.

### 2. High: the safety blackout is a downstream symptom of step overruns

The safety monitor checks whether DMX/ILDA frame counters are still advancing and blackouts when they do not move for long enough.

Relevant code:

- safety monitor creation: [builder.py](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/graph/builder.py:358)
- `max_silence=max(0.5 * heartbeat_timeout_s, 0.05)`: [builder.py](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/graph/builder.py:362)
- stall detection and blackout: [safety_interlock.py](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/graph/nodes/safety_interlock.py:581), [safety_interlock.py](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/graph/nodes/safety_interlock.py:587)

Because feature extraction overruns the frame budget by 5x to 15x, output threads stop seeing timely new frames and the watchdog fires. The watchdog is not the cause; it is exposing the cause.

### 3. High: blaming the current uncommitted `feature_extract.py` diff is not supported

The current worktree diff does **not** explain the reproduced failure:

- direct extractor call succeeds under both Python 3.12 and 3.14
- current and `HEAD` have essentially the same large-buffer cost profile
- current worktree is actually safer for very short windows than `HEAD`

Relevant code:

- current guarded short-window path: [feature_extract.py](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/graph/nodes/feature_extract.py:191)
- expensive calls still present in both versions: [feature_extract.py](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/graph/nodes/feature_extract.py:192), [feature_extract.py](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/graph/nodes/feature_extract.py:199), [feature_extract.py](/home/antoniofortes/Projects/laser_show_xdj_az/src/photonic_synesthesia/graph/nodes/feature_extract.py:226)

### 4. Medium: the Python 3.14 vs 3.12 split is real, but it is not the reproduced root cause

The bare command resolves to Python 3.14.3 and the repo venv is Python 3.12.13. That mismatch matters operationally and should be normalized, but it did **not** produce a failure in the isolated extractor test and it did **not** explain the reproduced steady-state stall.

This is environment debt, not the confirmed root cause of the current runtime failure.

### 5. Medium: the pasted `'float' object is not callable'` and segfault remain unverified on the current tree

I did not reproduce either:

- `'float' object is not callable'`
- segmentation fault

Given the current evidence, those are either:

- from a stale local state not recreated here
- from an earlier worktree snapshot
- from a different code path than the current one under test

They should not be used as the primary remediation target until reproduced.

### 6. Medium: button interactions are still risk multipliers, but they are not required for failure

Earlier reviews already established that the web-panel selection controls can synchronously block on regeneration and that some range controls are overly chatty. Those issues still matter, but the new destructive finding is stronger:

- the runtime already misses its frame budget before any UI action
- button-triggered regeneration can worsen an already overloaded loop, but it is not the origin of the overload

## Root Cause Statement

The confirmed root cause is that `run-file` tries to execute a full-frame feature extraction stack on every `20ms` tick while recomputing against a rolling audio window that grows to `2.0s`. The expensive librosa calls, especially `pyin`, `hpss`, and harmonic extraction, push `feature_extract` far beyond the frame budget. That starves output updates, triggers the safety watchdog, makes playback appear hung, and explains why the terminal can look stuck even without any UI interaction.

## Incorrect Prior Conclusions

The following claims are **not supported** by the fresh evidence:

- "The current uncommitted `feature_extract.py` diff is the culprit."
- "Python 3.14 alone explains the crash."
- "The button workflow is required to trigger the failure."
- "The current root cause is already identified as `'float' object is not callable'` in `feature_extract.py`."

## What Is Actually True Right Now

- The bare `photonic` command does use Python `3.14.3`.
- The repo venv uses Python `3.12.13`.
- The current `run-file` path is already overloaded without user interaction.
- `feature_extract` is the dominant cost center.
- The uncommitted worktree diff is not the demonstrated source of the overload.

## Remediation Priority

1. Stop recomputing the full heavy feature stack on every `20ms` frame.
2. Separate cheap realtime features from expensive periodic analysis.
3. Reduce or amortize `pyin`, `hpss`, and harmonic-analysis frequency.
4. Only after that, revisit UI-triggered regeneration and environment normalization.

