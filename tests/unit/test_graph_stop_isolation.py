"""Regression tests for graph.stop() per-node exception isolation (cycle-6 C2).

Pre-C2, a single node whose stop() raised prevented every subsequent
node from being torn down. Now that node stops use `join_or_raise` and
can legitimately raise on a wedged worker, the graph teardown must
isolate failures so:

  - every node gets a chance to clean up
  - the original exception(s) are logged loudly
  - stop() returns normally so the caller (cli.py finally block) can
    continue with its remaining cleanup (web server, shared context).
"""

from __future__ import annotations

from unittest import mock

from photonic_synesthesia.graph.builder import PhotonicGraph


def _make_empty_graph() -> PhotonicGraph:
    graph = PhotonicGraph.__new__(PhotonicGraph)
    graph.nodes = {}
    graph.safety_monitor = None
    graph._running = True
    graph._enable_watchdog = False
    graph._tick_number = 0
    graph._watchdog_shmem = None
    graph._watchdog_proc = None
    return graph


def test_stop_continues_after_one_node_raises() -> None:
    """Core C2 invariant: if cv_sense.stop() raises (e.g., its worker
    wedged and join_or_raise fired), dmx_output.stop() and every
    later step MUST still run."""
    graph = _make_empty_graph()

    # Three nodes in shutdown order: cv_sense (first in the pipeline
    # that actually appears), ilda_transport, dmx_output. Make the
    # middle one raise.
    cv_node = mock.MagicMock()
    ilda_node = mock.MagicMock()
    ilda_node.stop.side_effect = RuntimeError("ilda_transport wedged")
    dmx_node = mock.MagicMock()

    graph.nodes = {
        "cv_sense": cv_node,
        "ilda_transport": ilda_node,
        "dmx_output": dmx_node,
    }

    graph.stop()

    cv_node.stop.assert_called_once()
    ilda_node.stop.assert_called_once()
    dmx_node.stop.assert_called_once(), (
        "dmx_output.stop MUST run even after ilda_transport.stop raised"
    )


def test_stop_isolates_multiple_failures_and_logs_each() -> None:
    """Two nodes both fail. Both failures must be logged; every other
    node must still stop."""
    graph = _make_empty_graph()
    failing_a = mock.MagicMock()
    failing_a.stop.side_effect = RuntimeError("a")
    failing_b = mock.MagicMock()
    failing_b.stop.side_effect = RuntimeError("b")
    passing = mock.MagicMock()

    graph.nodes = {
        "cv_sense": failing_a,
        "dmx_output": failing_b,
        "ilda_export": passing,
    }

    with mock.patch("photonic_synesthesia.graph.builder.logger") as fake_log:
        graph.stop()

    passing.stop.assert_called_once()
    # logger.exception fires once per failed node.
    assert fake_log.exception.call_count == 2
    # The trailing summary log fires once with the count + names.
    fake_log.error.assert_called_once()
    call_kwargs = fake_log.error.call_args.kwargs
    assert call_kwargs["count"] == 2
    assert set(call_kwargs["nodes"]) == {"cv_sense", "dmx_output"}


def test_stop_returns_normally_even_when_every_node_fails() -> None:
    """Defence in depth: graph.stop() is called from a finally block.
    It must NEVER raise, or it would mask the original exception that
    triggered the shutdown."""
    graph = _make_empty_graph()
    n1 = mock.MagicMock()
    n1.stop.side_effect = RuntimeError("boom")
    n2 = mock.MagicMock()
    n2.stop.side_effect = RuntimeError("boom")
    graph.nodes = {"cv_sense": n1, "dmx_output": n2}

    # Must not raise.
    graph.stop()


def test_stop_skips_nodes_without_the_expected_method() -> None:
    """Historical resilience: some test doubles / minimal graphs omit
    .stop() on certain nodes. The per-step filter must skip rather
    than AttributeError through the try/except."""
    graph = _make_empty_graph()
    # A fake "node" that has no .stop attribute at all.
    minimal_node = object()
    real_node = mock.MagicMock()
    graph.nodes = {"cv_sense": minimal_node, "dmx_output": real_node}

    graph.stop()  # must not raise

    real_node.stop.assert_called_once()
