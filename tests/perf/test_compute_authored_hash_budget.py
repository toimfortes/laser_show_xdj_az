"""Perf pin for `_compute_authored_hash` under the graph-tick budget.

Cycle-5 panel A11 resolution: the cycle-1 plan claimed the hash
computation cost was 40-80 ms on a realistic show. Codex's cycle-1
review benchmarked it at 0.942 ms on the same repo. This test pins
the CURRENT cost so a future regression (new expensive field added
to the hash, slow-hash regression, etc.) is caught before it blows
the 50 Hz / 20 ms graph-tick budget.

If this test fails with a time > the pin, the A11 rework (deepcopy
reduction in `_replace_show_sections_locked`, or xxhash if still
needed) kicks in — driven by measurement, not speculation.
"""

from __future__ import annotations

import copy
import time
from typing import Any

import pytest


# Realistic 5-min show fixture: 10 sections, 20 flags, nested payloads
# matching the shape AI scorer + recipe library produces. Size ~50-100KB
# when serialized.
def _synthetic_section(index: int) -> dict[str, Any]:
    return {
        "id": f"sec-{index:03d}",
        "section_role": "drop" if index % 3 == 0 else "verse",
        "start_seconds": float(index * 30),
        "end_seconds": float((index + 1) * 30),
        "fixture_mode": "peak_return" if index % 2 else "build",
        "scene_id": "drop_intense",
        "laser_pattern": "fan_burst",
        "mover_pattern": "pan_sweep",
        "wash_pattern": "static",
        "led_pattern": "chase",
        "intensity_multiplier": 0.85,
        "motion_multiplier": 1.2,
        "strobe_level": 0.3 if index % 4 == 0 else 0.0,
        "laser_enabled": True,
        "movers_enabled": True,
        "washes_enabled": True,
        "leds_enabled": True,
        "cue_recipe": {
            "pattern": "burst_drop",
            "launch": {"geometry_family": "fan", "color_mode": "primary_saturated"},
            "sustain": [
                {"beat": 1, "intensity": 0.9, "motion": "fast"},
                {"beat": 2, "intensity": 1.0, "motion": "faster"},
                {"beat": 3, "intensity": 0.85, "motion": "fast"},
                {"beat": 4, "intensity": 1.0, "motion": "fastest"},
            ],
            "fill": {"density": 0.75, "direction": "outward"},
            "release": {"fade_ms": 250, "tail": "smooth"},
            "tags": [f"tag-{t}" for t in range(8)],
            "zones": {
                "crowd": {"policy": "overhead_only", "brightness_cap": 1.0},
                "stage": {"policy": "mixed_air", "brightness_cap": 0.8},
            },
        },
        "laser_program": {
            "pattern": "tunnel_burst",
            "launch": [
                {"geometry": "fan", "speed": 0.8, "color": [255, 100, 50]},
            ],
            "sustain": [
                {"beat": b, "motion": "fast", "color_shift": 0.1 * b, "size": 0.9}
                for b in range(1, 9)
            ],
            "fill": {"pattern": "noise", "density": 0.6},
            "release": {"fade_pattern": "exp", "decay_ms": 500},
        },
        "metadata": {
            "structure_marker": f"marker-{index}",
            "notes": "authored in cycle-2 test fixture",
            "confidence": 0.82,
        },
    }


def _synthetic_flag(index: int) -> dict[str, Any]:
    return {
        "id": f"flag-{index:03d}",
        "kind": "build" if index % 2 else "drop",
        "at_seconds": float(index * 15),
        "payload": {
            "source_section": f"sec-{index // 2:03d}",
            "transition_ms": 120,
            "weight": 1.0,
        },
    }


@pytest.fixture
def realistic_show_fixture() -> dict[str, Any]:
    return {
        "show_sections": [_synthetic_section(i) for i in range(10)],
        "timeline_flags": [_synthetic_flag(i) for i in range(20)],
        "staged_look": None,
    }


# Cycle-5 A11 panel floor: current measured cost is ~0.9 ms. Pin at
# 5 ms (5x headroom) to catch real regressions without flaking on
# CI under load. If this bar is ever breached, investigate the real
# bottleneck (deepcopy in `_replace_show_sections_locked`, not the
# hash itself).
_HASH_BUDGET_MS = 5.0
_HASH_WARMUP = 3
_HASH_ITERATIONS = 20


def test_compute_authored_hash_under_5ms_for_realistic_show(realistic_show_fixture):
    """Cycle-5 panel A11 regression gate. Pins the current sub-1ms
    cost; fails loud if a future change pushes the computation over
    5ms (25% of the graph-tick budget)."""
    from photonic_synesthesia.platform.runtime_context import _compute_authored_hash

    sections = realistic_show_fixture["show_sections"]
    flags = realistic_show_fixture["timeline_flags"]
    staged = realistic_show_fixture["staged_look"]

    # Warm-up (prime import caches, JIT if any)
    for _ in range(_HASH_WARMUP):
        _compute_authored_hash(sections, flags, staged)

    # Measure
    times_ms = []
    for _ in range(_HASH_ITERATIONS):
        t0 = time.perf_counter()
        _compute_authored_hash(sections, flags, staged)
        times_ms.append((time.perf_counter() - t0) * 1000)

    times_ms.sort()
    median = times_ms[len(times_ms) // 2]
    p95 = times_ms[int(len(times_ms) * 0.95)]

    assert median < _HASH_BUDGET_MS, (
        f"_compute_authored_hash regressed. median={median:.2f}ms p95={p95:.2f}ms "
        f"budget={_HASH_BUDGET_MS}ms. Inspect recent changes to "
        "_compute_authored_hash or add xxhash + revision-gate rework per "
        "docs/superpowers/plans/2026-04-20-deferred-criticals-plan.md."
    )
    assert p95 < _HASH_BUDGET_MS * 2, (
        f"_compute_authored_hash p95={p95:.2f}ms exceeded 2x budget; tail latency "
        "risk for the graph tick."
    )


def test_replace_show_sections_locked_under_10ms_for_realistic_show(realistic_show_fixture):
    """Cycle-5 panel A11 secondary gate. `_replace_show_sections_locked`
    includes hash recompute + TWO `copy.deepcopy` of the full show
    sections list (lines 354, 358 of runtime_context.py). Kilo's
    analysis flagged this as the real bottleneck. If this ever
    regresses, that's the spot to attack."""
    from photonic_synesthesia.platform.runtime_context import PlaybackContext

    ctx = PlaybackContext(
        file_path="/tmp/test.wav",
        file_name="test.wav",
        duration_seconds=300.0,
    )
    ctx._save_callback = lambda payload: None
    sections = realistic_show_fixture["show_sections"]

    # Warm
    for _ in range(_HASH_WARMUP):
        ctx._replace_show_sections_locked(copy.deepcopy(sections))

    times_ms = []
    for _ in range(_HASH_ITERATIONS):
        fresh = copy.deepcopy(sections)  # caller-owned input
        t0 = time.perf_counter()
        ctx._replace_show_sections_locked(fresh)
        times_ms.append((time.perf_counter() - t0) * 1000)

    times_ms.sort()
    median = times_ms[len(times_ms) // 2]
    # 10ms gives room for the deepcopy work; if this fails, the cycle-2
    # plan's "deepcopy reduction" fallback kicks in.
    assert median < 10.0, (
        f"_replace_show_sections_locked median={median:.2f}ms exceeded 10ms. "
        "Likely deepcopy regression; see cycle-2 plan §A11 Phase 2."
    )
