"""Regression tests for E3: handle-before-init-complete leaks.

Three variants of the same pattern caught by panel v2:
  - H1: artnet.open() — `setsockopt` failure leaks socket FD.
  - H3: ether_dream.connect() — `_socket` assigned before handshake;
    failure poisons it and blocks reconnect.
  - H5: audio_sense.start() — `InputStream.start()` failure leaks
    PortAudio handle and blocks future starts.

Test contract: on initialization failure, NO partially-opened handle
is retained as instance state, AND a subsequent retry can succeed.
"""

from __future__ import annotations

from unittest import mock

import pytest

from photonic_synesthesia.dmx.artnet import ArtNetTransmitter


def test_artnet_open_closes_socket_when_setsockopt_fails() -> None:
    """H1 invariant: if setsockopt raises, the constructed socket
    must be closed. Otherwise the FD leaks until GC and self._socket
    stays None — the next open() retries cleanly."""
    transmitter = ArtNetTransmitter(host="192.168.1.255", broadcast=True)
    fake_sock = mock.MagicMock()
    fake_sock.setsockopt.side_effect = OSError("broadcast denied")

    with mock.patch(
        "photonic_synesthesia.dmx.artnet.socket.socket", return_value=fake_sock
    ):
        with pytest.raises(OSError, match="broadcast denied"):
            transmitter.open()

    fake_sock.close.assert_called_once()
    assert transmitter._socket is None, "transmitter must NOT retain partial socket"


def test_artnet_open_can_retry_after_setsockopt_failure() -> None:
    """H1 invariant continued: after a failed open(), a subsequent
    open() with a healthy socket constructor succeeds."""
    transmitter = ArtNetTransmitter(host="192.168.1.255", broadcast=True)
    bad_sock = mock.MagicMock()
    bad_sock.setsockopt.side_effect = OSError("transient")
    good_sock = mock.MagicMock()
    socket_factory = mock.MagicMock(side_effect=[bad_sock, good_sock])

    with mock.patch("photonic_synesthesia.dmx.artnet.socket.socket", socket_factory):
        with pytest.raises(OSError):
            transmitter.open()
        # Second open MUST succeed — partial state didn't poison us.
        transmitter.open()

    assert transmitter._socket is good_sock
    bad_sock.close.assert_called_once()


def test_ether_dream_connect_does_not_poison_socket_on_handshake_failure() -> None:
    """H3 invariant: if `_recv_response()` raises mid-handshake,
    `self._socket` MUST be None. Pre-E3 it stayed set, and every
    subsequent connect() short-circuited on the `is not None` check."""
    from photonic_synesthesia.core.config import ILDAConfig
    from photonic_synesthesia.laser.ether_dream import EtherDreamClient

    config = ILDAConfig(
        enabled=True,
        transport_type="ether_dream",
        ether_dream_host="192.0.2.1",
        ether_dream_port=7765,
        ether_dream_timeout_s=0.1,
    )
    client = EtherDreamClient(config)

    fake_sock = mock.MagicMock()

    with (
        mock.patch(
            "photonic_synesthesia.laser.ether_dream.socket.create_connection",
            return_value=fake_sock,
        ),
        mock.patch.object(
            EtherDreamClient,
            "_recv_response",
            side_effect=TimeoutError("DAC timed out during handshake"),
        ),
    ):
        with pytest.raises(TimeoutError, match="DAC timed out"):
            client.connect()

    assert client._socket is None, (
        "EtherDreamClient must NOT retain a poisoned socket after a failed "
        "handshake — otherwise reconnect short-circuits forever"
    )
    fake_sock.close.assert_called_once()


def test_ether_dream_connect_retries_cleanly_after_handshake_failure() -> None:
    """H3 invariant continued: a follow-up connect() with a working
    handshake must succeed (proves we cleared partial state)."""
    from photonic_synesthesia.core.config import ILDAConfig
    from photonic_synesthesia.laser.ether_dream import EtherDreamClient

    config = ILDAConfig(
        enabled=True,
        transport_type="ether_dream",
        ether_dream_host="192.0.2.1",
        ether_dream_port=7765,
        ether_dream_timeout_s=0.1,
    )
    client = EtherDreamClient(config)

    bad_sock = mock.MagicMock()
    good_sock = mock.MagicMock()
    socket_factory = mock.MagicMock(side_effect=[bad_sock, good_sock])

    recv_calls = {"n": 0}
    def _recv(self_) -> object:
        recv_calls["n"] += 1
        if recv_calls["n"] == 1:
            raise TimeoutError("first attempt fails")
        return None

    with (
        mock.patch(
            "photonic_synesthesia.laser.ether_dream.socket.create_connection",
            socket_factory,
        ),
        mock.patch.object(EtherDreamClient, "_recv_response", _recv),
    ):
        with pytest.raises(TimeoutError):
            client.connect()
        # Now retry — must succeed.
        client.connect()

    assert client._socket is good_sock
    bad_sock.close.assert_called_once()


def test_audio_sense_start_closes_stream_when_start_fails() -> None:
    """H5 invariant: if `InputStream.start()` raises (device removed
    after query but before start), the constructed stream must be
    closed. Otherwise `self._stream` stays truthy and future
    `start()` short-circuits the early-return guard."""
    from photonic_synesthesia.core.config import AudioConfig
    from photonic_synesthesia.graph.nodes.audio_sense import AudioSenseNode

    fake_stream = mock.MagicMock()
    fake_stream.start.side_effect = OSError("PortAudio: device gone")
    fake_input_stream_cls = mock.MagicMock(return_value=fake_stream)

    with mock.patch(
        "photonic_synesthesia.graph.nodes.audio_sense.SOUNDDEVICE_AVAILABLE", True
    ), mock.patch(
        "photonic_synesthesia.graph.nodes.audio_sense.sd"
    ) as fake_sd:
        fake_sd.InputStream = fake_input_stream_cls
        node = AudioSenseNode(AudioConfig(device=""))
        with pytest.raises(Exception):
            node.start()

    fake_stream.close.assert_called_once()
    assert node._stream is None, (
        "AudioSenseNode must NOT retain a partially-opened PortAudio stream"
    )
