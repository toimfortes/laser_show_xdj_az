"""Regression tests for midi_sense stop/callback ordering (cycle-6 C1).

Pre-C1, stop() called `port.close()` first and set `_running = False`
last. The rtmidi reader thread could fire `_on_message` with a
message whose buffer was about to be freed, and `put_nowait` would
enqueue a message with a stale handle — cleanup-time ghost events.
"""

from __future__ import annotations

from unittest import mock

import pytest

from photonic_synesthesia.core.config import MidiConfig
from photonic_synesthesia.graph.nodes.midi_sense import MidiSenseNode


def test_callback_after_stop_is_discarded_not_enqueued() -> None:
    """Core C1 invariant: a callback firing AFTER stop() flipped
    `_running` must early-return, not put a stale message onto the
    queue."""
    node = MidiSenseNode(MidiConfig())
    fake_port = mock.MagicMock()
    node._port = fake_port
    node._running = True

    node.stop()

    assert not node._running
    assert node._port is None
    fake_port.close.assert_called_once()

    # Now simulate the rtmidi reader firing a late callback.
    stale_msg = mock.MagicMock()
    node._on_message(stale_msg)

    assert node._message_queue.empty(), (
        "post-stop callback must NOT enqueue a message — _running gate failed"
    )


def test_stop_is_idempotent_and_safe_under_double_call() -> None:
    """The graph stop path and atexit can both end up invoking stop().
    Must not raise on the second call."""
    node = MidiSenseNode(MidiConfig())
    fake_port = mock.MagicMock()
    node._port = fake_port
    node._running = True

    node.stop()
    node.stop()  # second call — must not raise

    fake_port.close.assert_called_once(), "port.close must only run once"


def test_stop_survives_port_close_exception() -> None:
    """If the underlying mido port raises on close (rtmidi in a bad
    state), stop() must still clear `_running` and `_port` so a later
    start() doesn't see a zombie handle."""
    node = MidiSenseNode(MidiConfig())
    fake_port = mock.MagicMock()
    fake_port.close.side_effect = OSError("rtmidi wedged")
    node._port = fake_port
    node._running = True

    node.stop()  # must not raise

    assert node._port is None
    assert not node._running


def test_start_refuses_to_double_start_when_port_is_live() -> None:
    """Mirror the cycle-6 A1/B1 double-start guards: if a previous
    start() left a live port (or stop() hasn't run), a second start
    must refuse instead of leaking a second reader thread."""
    node = MidiSenseNode(MidiConfig())
    node._port = mock.MagicMock()  # simulate a live port
    node._running = True

    with pytest.raises(RuntimeError, match="refusing to double-start"):
        node.start()
