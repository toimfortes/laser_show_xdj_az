"""Regression tests for ILDADACOutputNode hang-remediation (cycle-6 B2).

Pins:
  - `stop()` raises if the emergency thread fails to exit (was silent).
  - `start()` refuses to double-start when a zombie thread is alive.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from photonic_synesthesia.core.config import (
    FixtureConfig,
    ILDAConfig,
    LaserSafetyConfig,
)
from photonic_synesthesia.graph.nodes.ilda_output import ILDADACOutputNode


def _build_node() -> ILDADACOutputNode:
    fixture = FixtureConfig(
        id="laser-main",
        name="Laser Main",
        type="laser",
        profile="laser_aucd_cx338b_hybrid",
        start_address=1,
        enabled=True,
    )
    fake_client = MagicMock()
    with patch(
        "photonic_synesthesia.graph.nodes.ilda_output.EtherDreamClient",
        return_value=fake_client,
    ):
        node = ILDADACOutputNode(
            ILDAConfig(enabled=True, transport_type="ether_dream", target_fps=25.0),
            LaserSafetyConfig(),
            [fixture],
        )
    return node


def test_ilda_dac_start_refuses_to_double_start() -> None:
    node = _build_node()
    with patch(
        "photonic_synesthesia.graph.nodes.ilda_output.EtherDreamClient",
        return_value=MagicMock(),
    ):
        node.start()
    try:
        with pytest.raises(RuntimeError, match="refusing to double-start"):
            node.start()
    finally:
        node.stop()


def test_ilda_dac_stop_is_loud_when_emergency_thread_wedges() -> None:
    node = _build_node()
    wedge = threading.Event()
    # Replace the emergency thread with an unkillable one.
    worker = threading.Thread(
        target=lambda: wedge.wait(5.0), name="ILDA-Emergency-Output", daemon=True
    )
    worker.start()
    node._thread = worker

    try:
        with pytest.raises(RuntimeError, match="ILDA-Emergency-Output.*failed to exit"):
            node.stop()
    finally:
        # `stop()` nulls `node._thread` in its finally block; keep our
        # own ref to drain the wedged worker before the canary checks.
        wedge.set()
        worker.join(timeout=1.0)


def test_ilda_dac_stop_still_closes_client_when_join_raises() -> None:
    """A wedged emergency thread must not strand the Ether Dream client."""
    node = _build_node()
    wedge = threading.Event()
    worker = threading.Thread(
        target=lambda: wedge.wait(5.0), name="ILDA-Emergency-Output", daemon=True
    )
    worker.start()
    node._thread = worker
    fake_client = MagicMock()
    node._ether_dream = fake_client

    try:
        with pytest.raises(RuntimeError, match="ILDA-Emergency-Output.*failed to exit"):
            node.stop()
    finally:
        wedge.set()
        worker.join(timeout=1.0)

    fake_client.stop.assert_called_once()
    fake_client.close.assert_called_once()
    assert node._ether_dream is None


def test_ilda_dac_stop_returns_fast_under_clean_shutdown() -> None:
    node = _build_node()
    with patch(
        "photonic_synesthesia.graph.nodes.ilda_output.EtherDreamClient",
        return_value=MagicMock(),
    ):
        node.start()
    time.sleep(0.05)

    t0 = time.monotonic()
    node.stop()
    elapsed = time.monotonic() - t0
    assert elapsed < 0.3, f"stop took {elapsed*1000:.1f}ms — expected <300ms"
