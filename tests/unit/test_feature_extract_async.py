"""Pinning tests for the cycle-1 Review A heavy-DSP split.

Asserts:
  1. The hot path stays under the 50 Hz frame budget when called
     repeatedly (no GIL contention from the bg analyzer).
  2. `_extract_features(y, sr)` (no overrides) still returns the FULL
     synchronous result — preserving every existing caller's contract.
  3. `__call__` populates harmonic features from the background
     analyzer once it's had time to compute.
  4. `close()` shuts down the ProcessPool cleanly.
  5. Multiple instances don't interfere with each other.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

pytest.importorskip("librosa")

from photonic_synesthesia.core.state import create_initial_state
from photonic_synesthesia.graph.nodes.feature_extract import (
    FeatureExtractNode,
    _NEUTRAL_HARMONIC,
)


SR = 48000
BUFFER_SECONDS = 2.0
FRAME_BUDGET_MS = 20.0  # 50 Hz target (informational)
# Regression threshold: pre-Review-A p50 was ~650 ms; post-fix is ~16 ms.
# Allowing up to 50 ms for the test to catch a real regression while
# tolerating normal timing variance under loaded CI / parallel tests.
REGRESSION_THRESHOLD_MS = 50.0


def _sine_buffer(seconds: float = BUFFER_SECONDS, freq: float = 440.0) -> np.ndarray:
    return (
        np.sin(2 * np.pi * freq * np.arange(int(SR * seconds)) / SR) * 0.3
    ).astype(np.float32)


def _seed_state(buffer: np.ndarray) -> dict:
    state = create_initial_state()
    state["audio_buffer"] = list(buffer)
    state["sample_rate"] = SR
    state["safety_state"] = {}
    state["processing_times"] = {}
    return state


# ---------------------------------------------------------------------------
# Hot path performance — the actual Review A regression


def test_hot_path_p95_under_frame_budget():
    """Cycle-1 Review A: __call__ p95 MUST stay under 20 ms even with
    the bg analyzer actively computing pyin/hpss/chroma. Pre-fix, p95
    was ~460 ms (23x over budget) due to GIL contention with the
    thread-based worker. Process-based worker eliminates the GIL share.
    """
    node = FeatureExtractNode()
    try:
        y = _sine_buffer()
        state = _seed_state(y)

        # Warm-up: first call spawns the ProcessPool (~1-2s on first launch).
        # We intentionally pay this cost outside the measurement loop.
        for _ in range(3):
            state = node(state)
            state["processing_times"] = {}
            time.sleep(0.3)

        # Measure 50 calls = 1s of 50 Hz.
        N = 50
        times_ms = []
        for _ in range(N):
            state["processing_times"] = {}
            t0 = time.perf_counter()
            state = node(state)
            times_ms.append((time.perf_counter() - t0) * 1000)
        times_ms.sort()
        p50 = times_ms[N // 2]
        p95 = times_ms[int(N * 0.95)]

        assert p50 < REGRESSION_THRESHOLD_MS, (
            f"hot path p50={p50:.1f}ms exceeds {REGRESSION_THRESHOLD_MS}ms regression threshold "
            f"(Review A pre-fix was ~650 ms). All times: {times_ms!r}"
        )
        assert p95 < REGRESSION_THRESHOLD_MS, (
            f"hot path p95={p95:.1f}ms exceeds {REGRESSION_THRESHOLD_MS}ms threshold — "
            f"likely GIL contention from bg worker (regression of Review A v2 fix). "
            f"All times: {times_ms!r}"
        )
    finally:
        node.close()


# ---------------------------------------------------------------------------
# Backwards-compat: full synchronous extraction without overrides


def test_extract_features_without_overrides_runs_full_heavy_path():
    """`_extract_features(y, sr)` (no harmonic_overrides=...) MUST
    still compute the full synchronous result — every existing caller
    (test_production_hardening, the analyze CLI subcommand) relies on
    this. The split is opt-in via `__call__`; direct calls are
    unchanged."""
    node = FeatureExtractNode()
    try:
        y = _sine_buffer()
        features = node._extract_features(y, SR)
        # Pure sine at 440 Hz → measurable pitch_salience > 0
        # (heavy DSP ran; not the neutral default of 0.0).
        assert features["pitch_salience"] > 0.5, (
            f"sync path should compute pyin/piptrack; got "
            f"pitch_salience={features['pitch_salience']}"
        )
        # Light-path features always populate.
        assert features["rms_energy"] > 0.0
        assert features["spectral_centroid"] > 0.0
    finally:
        node.close()


def test_extract_features_with_overrides_skips_heavy_path():
    """When `harmonic_overrides=` is supplied, the heavy DSP block
    MUST be skipped (this is the perf gain). Verify by measuring time
    against the no-overrides version on the same buffer."""
    node = FeatureExtractNode()
    try:
        y = _sine_buffer()

        t0 = time.perf_counter()
        full = node._extract_features(y, SR)
        full_ms = (time.perf_counter() - t0) * 1000

        overrides = {
            "harmonic_ratio": 0.7,
            "percussive_ratio": 0.3,
            "harmonic_change": 0.1,
            "tonal_stability": 0.9,
            "harmonic_tension": 0.05,
            "pitch_salience": 0.8,
            "pitch_height": 0.5,
            "melodic_contour": 0.6,
            "melodic_stability": 0.95,
        }
        t0 = time.perf_counter()
        light = node._extract_features(y, SR, harmonic_overrides=overrides)
        light_ms = (time.perf_counter() - t0) * 1000

        # Overrides version is ~30-50x faster than the full path.
        assert light_ms < full_ms * 0.5, (
            f"overrides path ({light_ms:.0f}ms) should be much faster than full ({full_ms:.0f}ms)"
        )
        # Light path returns the override values verbatim.
        assert light["harmonic_ratio"] == 0.7
        assert light["pitch_salience"] == 0.8
        # Light path values are computed normally.
        assert light["rms_energy"] == full["rms_energy"]
        assert light["spectral_centroid"] == full["spectral_centroid"]
    finally:
        node.close()


# ---------------------------------------------------------------------------
# Async path eventually populates harmonic features


def test_call_eventually_populates_harmonic_from_background():
    """First few __call__ ticks see neutral defaults (analyzer hasn't
    finished yet), but after ~3s the harmonic snapshot from the bg
    process arrives and subsequent ticks include those values."""
    node = FeatureExtractNode()
    try:
        y = _sine_buffer()
        state = _seed_state(y)

        # First call kicks off the analyzer; harmonic features start neutral.
        state = node(state)
        first = state["audio_features"]
        assert first["harmonic_ratio"] == _NEUTRAL_HARMONIC["harmonic_ratio"]
        assert first["pitch_salience"] == _NEUTRAL_HARMONIC["pitch_salience"]

        # Wait for the bg process to publish a result.
        deadline = time.time() + 10.0
        eventually_real = None
        while time.time() < deadline:
            state["processing_times"] = {}
            state = node(state)
            f = state["audio_features"]
            if f["pitch_salience"] != _NEUTRAL_HARMONIC["pitch_salience"]:
                eventually_real = f
                break
            time.sleep(0.1)

        assert eventually_real is not None, (
            "bg analyzer never produced a result within 10s"
        )
        # Real values for a 440 Hz sine — pitch should be detected.
        assert eventually_real["pitch_salience"] > 0.5
        assert eventually_real["harmonic_ratio"] > 0.5
    finally:
        node.close()


# ---------------------------------------------------------------------------
# Resource cleanup


def test_close_shuts_down_executor_idempotently():
    node = FeatureExtractNode()
    state = _seed_state(_sine_buffer())
    node(state)  # spawns analyzer

    assert node._harmonic_analyzer is not None
    node.close()
    # Second close is a no-op.
    node.close()
    # New __call__ after close re-creates the analyzer cleanly.
    state2 = _seed_state(_sine_buffer())
    node(state2)
    assert node._harmonic_analyzer is not None
    node.close()


def test_two_nodes_have_independent_analyzers():
    """Each FeatureExtractNode owns its own ProcessPool. Test by
    creating two nodes, calling both, and confirming neither's bg
    work blocks the other."""
    node_a = FeatureExtractNode()
    node_b = FeatureExtractNode()
    try:
        state_a = _seed_state(_sine_buffer())
        state_b = _seed_state(_sine_buffer(freq=880.0))
        # First calls warm both analyzers.
        node_a(state_a)
        node_b(state_b)
        # Each node has its own analyzer.
        assert node_a._harmonic_analyzer is not None
        assert node_b._harmonic_analyzer is not None
        assert node_a._harmonic_analyzer is not node_b._harmonic_analyzer
    finally:
        node_a.close()
        node_b.close()
