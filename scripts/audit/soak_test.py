#!/usr/bin/env python3
"""Run a deterministic mock-soak test for the photonic graph."""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import time
from pathlib import Path
from typing import Any

import structlog

from photonic_synesthesia.core.config import Settings
from photonic_synesthesia.graph import build_photonic_graph


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    rank = (len(ordered) - 1) * q
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _series_stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {
            "count": 0.0,
            "mean_ms": 0.0,
            "p50_ms": 0.0,
            "p95_ms": 0.0,
            "p99_ms": 0.0,
            "max_ms": 0.0,
        }
    return {
        "count": float(len(values)),
        "mean_ms": statistics.fmean(values) * 1000.0,
        "p50_ms": _percentile(values, 0.50) * 1000.0,
        "p95_ms": _percentile(values, 0.95) * 1000.0,
        "p99_ms": _percentile(values, 0.99) * 1000.0,
        "max_ms": max(values) * 1000.0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run mock soak-test for graph stability")
    parser.add_argument("--duration-s", type=float, default=300.0)
    parser.add_argument("--target-fps", type=float, default=50.0)
    parser.add_argument("--frame-p99-budget-ms", type=float, default=25.0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config/pknight_single_laser.yaml"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING),
    )

    settings = Settings.from_yaml(args.config)
    graph = build_photonic_graph(settings=settings, mock_sensors=True)

    frame_durations_s: list[float] = []
    node_times_s: dict[str, list[float]] = {}
    exceptions: list[str] = []
    frame_interval = 1.0 / args.target_fps

    start = time.monotonic()
    deadline = start + args.duration_s

    try:
        graph.start()
        while time.monotonic() < deadline:
            frame_begin = time.perf_counter()
            try:
                state = graph.step()
            except Exception as exc:  # pragma: no cover - exercised in real soak runs
                exceptions.append(repr(exc))
                break
            elapsed = time.perf_counter() - frame_begin
            frame_durations_s.append(elapsed)

            for node, node_elapsed in state.get("processing_times", {}).items():
                node_times_s.setdefault(node, []).append(float(node_elapsed))

            remaining = frame_interval - elapsed
            if remaining > 0:
                if settings.runtime_flags.hybrid_pacing:
                    graph._sleep_with_hybrid_pacing(remaining)
                else:
                    time.sleep(remaining)
    finally:
        graph.stop()

    frame_stats = _series_stats(frame_durations_s)
    node_stats = {name: _series_stats(values) for name, values in node_times_s.items()}

    pass_no_exceptions = len(exceptions) == 0
    pass_frame_budget = frame_stats["p99_ms"] <= args.frame_p99_budget_ms

    report: dict[str, Any] = {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_s": args.duration_s,
        "target_fps": args.target_fps,
        "frame_p99_budget_ms": args.frame_p99_budget_ms,
        "frame_stats": frame_stats,
        "node_stats": node_stats,
        "exceptions": exceptions,
        "pass": {
            "no_unhandled_exceptions": pass_no_exceptions,
            "frame_p99_within_budget": pass_frame_budget,
            "overall": pass_no_exceptions and pass_frame_budget,
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(report["pass"], indent=2))
    return 0 if report["pass"]["overall"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
