"""Regression tests for dmx_test CLI hang-remediation (cycle-6 A5).

Pins:
  - `--max-duration` bounds the run and invokes blackout/stop at timeout.
  - Pre-A5 this command had `while True: time.sleep(1)` with no way to
    exit from CI; a wrapper had to SIGKILL, which skipped blackout.
"""

from __future__ import annotations

import time
from unittest import mock

from click.testing import CliRunner

from photonic_synesthesia.ui.cli import cli


def test_dmx_test_max_duration_exits_cleanly_and_blackouts() -> None:
    """Core A5 invariant: --max-duration=N must cause clean exit
    after N seconds with blackout() + stop() called in finally."""
    mock_node = mock.MagicMock()
    mock_node.start.return_value = None

    with mock.patch(
        "photonic_synesthesia.graph.nodes.dmx_output.DMXOutputNode",
        return_value=mock_node,
    ):
        runner = CliRunner()
        t0 = time.monotonic()
        result = runner.invoke(
            cli, ["dmx-test", "-c", "1", "-v", "100", "--max-duration", "0.2"]
        )
        elapsed = time.monotonic() - t0

    assert result.exit_code == 0, f"exit_code={result.exit_code}, output={result.output}"
    # Allow ~0.6s slack for CI noise — the important thing is it's
    # bounded, not infinite.
    assert 0.15 <= elapsed < 2.0, f"took {elapsed:.2f}s — expected ~0.2s"
    mock_node.blackout.assert_called_once()
    mock_node.stop.assert_called_once()
    assert "Max duration" in result.output


def test_dmx_test_max_duration_zero_returns_immediately() -> None:
    """Edge case: --max-duration=0 must not hang."""
    mock_node = mock.MagicMock()
    mock_node.start.return_value = None

    with mock.patch(
        "photonic_synesthesia.graph.nodes.dmx_output.DMXOutputNode",
        return_value=mock_node,
    ):
        runner = CliRunner()
        t0 = time.monotonic()
        result = runner.invoke(
            cli, ["dmx-test", "-c", "1", "-v", "100", "--max-duration", "0"]
        )
        elapsed = time.monotonic() - t0

    assert result.exit_code == 0
    assert elapsed < 1.0, f"took {elapsed:.2f}s — expected <1s"
    mock_node.blackout.assert_called_once()
    mock_node.stop.assert_called_once()


def test_dmx_test_restores_previous_signal_handlers() -> None:
    """A5: the command installs SIGINT/SIGTERM handlers to wake the
    wait. Those must be restored on exit so later code in the same
    process isn't affected."""
    import signal

    sentinel_sigint = signal.getsignal(signal.SIGINT)
    sentinel_sigterm = signal.getsignal(signal.SIGTERM)

    mock_node = mock.MagicMock()
    mock_node.start.return_value = None

    with mock.patch(
        "photonic_synesthesia.graph.nodes.dmx_output.DMXOutputNode",
        return_value=mock_node,
    ):
        runner = CliRunner()
        result = runner.invoke(
            cli, ["dmx-test", "-c", "1", "-v", "100", "--max-duration", "0.05"]
        )

    assert result.exit_code == 0
    assert signal.getsignal(signal.SIGINT) == sentinel_sigint
    assert signal.getsignal(signal.SIGTERM) == sentinel_sigterm
