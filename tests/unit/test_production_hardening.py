"""
Regression tests for production-hardening changes.

Covers:
- Finite-value guard in DMX output (NaN/Inf rejection)
- Art-Net blackout sent on stop()
- Safety interlock applied before DMX output (fixture_commands clamping)
- CLI dmx_test cleanup on non-KeyboardInterrupt exceptions
- SIGTERM handler wires into graph.stop()
"""

from __future__ import annotations

import math
import signal
import unittest.mock as mock
import wave
from pathlib import Path

import pytest

from photonic_synesthesia.core.config import (
    DMXConfig,
    FixtureConfig,
    LaserSafetyConfig,
    SafetyConfig,
)
from photonic_synesthesia.core.state import FixtureCommand, create_initial_state
from photonic_synesthesia.dmx.universe import DMX_START_CODE, create_universe_buffer
from photonic_synesthesia.graph.nodes.dmx_output import DMXOutputNode
from photonic_synesthesia.graph.nodes.safety_interlock import SafetyInterlockNode


def _armed_state():
    state = create_initial_state()
    state["control_state"]["armed_live"] = True
    return state


# ---------------------------------------------------------------------------
# Finite-value guard
# ---------------------------------------------------------------------------


def test_dmx_output_rejects_nan_channel_value() -> None:
    """NaN values must be silently dropped; existing channels stay unchanged."""
    node = DMXOutputNode(DMXConfig(interface_type="artnet"))
    state = _armed_state()
    state["fixture_commands"] = [
        FixtureCommand(
            fixture_id="fx1",
            fixture_type="laser",
            channel_values={
                1: 100,
                2: math.nan,
            },
        )
    ]

    result = node(state)
    universe = result["dmx_universe"]

    assert universe[1] == 100, "Valid channel should be written"
    assert universe[2] == 0, "NaN channel must be ignored (stays at 0)"
    assert universe[0] == DMX_START_CODE, "Start code must remain intact"


def test_dmx_output_rejects_inf_channel_value() -> None:
    """Inf values must be silently dropped; existing channels stay unchanged."""
    node = DMXOutputNode(DMXConfig(interface_type="artnet"))
    state = _armed_state()
    state["fixture_commands"] = [
        FixtureCommand(
            fixture_id="fx1",
            fixture_type="laser",
            channel_values={
                3: 50,
                4: math.inf,
                5: -math.inf,
            },
        )
    ]

    result = node(state)
    universe = result["dmx_universe"]

    assert universe[3] == 50
    assert universe[4] == 0, "+Inf must be rejected"
    assert universe[5] == 0, "-Inf must be rejected"


def test_dmx_output_request_blackout_latches_zero_universe() -> None:
    node = DMXOutputNode(DMXConfig(interface_type="artnet"))
    state = _armed_state()
    state["fixture_commands"] = [
        FixtureCommand(
            fixture_id="fx1",
            fixture_type="laser",
            channel_values={1: 255, 2: 127},
        )
    ]
    node(state)
    assert node.get_stats()["blackout_requested"] is False

    node.request_blackout()
    state = _armed_state()
    state["fixture_commands"] = [
        FixtureCommand(
            fixture_id="fx1",
            fixture_type="laser",
            channel_values={1: 255},
        )
    ]
    result = node(state)

    assert result["dmx_universe"][1] == 0
    assert result["dmx_universe"][2] == 0
    assert node.get_stats()["blackout_requested"] is True


# ---------------------------------------------------------------------------
# Art-Net blackout on stop
# ---------------------------------------------------------------------------


def test_dmx_output_artnet_sends_blackout_on_stop() -> None:
    """stop() must transmit a zero-filled packet over Art-Net before closing."""
    config = DMXConfig(interface_type="artnet")
    node = DMXOutputNode(config)

    sent_packets: list[bytes] = []

    mock_artnet = mock.MagicMock()
    mock_artnet.send_dmx.side_effect = lambda universe, dmx_data, sequence: sent_packets.append(
        bytes(dmx_data)
    )

    # Inject a running Art-Net transmitter without actually opening a socket
    node._artnet = mock_artnet
    node._running = False  # transmit thread not started
    node._thread = None

    node.stop()

    assert mock_artnet.close.called, "ArtNetTransmitter.close() must be called"
    assert len(sent_packets) >= 1, "At least one blackout packet must be sent"
    assert sent_packets[-1] == bytes(512), "Final packet must be all zeros (blackout)"


# ---------------------------------------------------------------------------
# Safety interlock clamps fixture_commands (now runs before dmx_output)
# ---------------------------------------------------------------------------


def test_safety_interlock_clamps_fixture_commands_y_axis() -> None:
    """When safety interlock runs before dmx_output it must clamp fixture_commands."""
    fixture = FixtureConfig(
        id="laser-1",
        name="Laser 1",
        type="laser",
        profile="laser_generic_7ch",
        start_address=10,
        enabled=True,
    )
    safety = SafetyConfig(
        laser=LaserSafetyConfig(
            y_axis_max=100,
            min_scan_speed=30,
            y_channel_offset=1,
            speed_channel_offset=2,
        )
    )
    node = SafetyInterlockNode(config=safety, fixtures=[fixture])

    state = create_initial_state()
    state["beat_info"]["confidence"] = 1.0
    # dmx_universe starts zeroed (as it would when running before dmx_output)
    state["dmx_universe"] = bytes(create_universe_buffer())
    state["fixture_commands"] = [
        FixtureCommand(
            fixture_id="laser-1",
            fixture_type="laser",
            channel_values={
                11: 240,  # y_channel (start_address=10, y_offset=1)  -> should clamp to 100
                12: 5,    # speed_channel (start_address=10, speed_offset=2) -> clamp to 30
            },
        )
    ]

    result = node(state)

    cmd = result["fixture_commands"][0]
    assert cmd["channel_values"][11] == 100, "Y-axis must be clamped to y_axis_max"
    assert cmd["channel_values"][12] == 30, "Scan speed must be raised to min_scan_speed"


def test_safety_interlock_leaves_non_laser_commands_unchanged() -> None:
    """Safety interlock must not modify fixture_commands for non-laser fixtures."""
    fixture = FixtureConfig(
        id="laser-1",
        name="Laser 1",
        type="laser",
        profile="laser_generic_7ch",
        start_address=10,
        enabled=True,
    )
    safety = SafetyConfig(laser=LaserSafetyConfig(y_axis_max=100, y_channel_offset=1))
    node = SafetyInterlockNode(config=safety, fixtures=[fixture])

    state = create_initial_state()
    state["beat_info"]["confidence"] = 1.0
    state["dmx_universe"] = bytes(create_universe_buffer())
    state["fixture_commands"] = [
        FixtureCommand(
            fixture_id="panel-1",
            fixture_type="panel",
            channel_values={50: 200},
        )
    ]

    result = node(state)
    assert result["fixture_commands"][0]["channel_values"][50] == 200


# ---------------------------------------------------------------------------
# Graph builder: start() inside try/finally
# ---------------------------------------------------------------------------


def test_graph_stop_called_if_start_raises() -> None:
    """If start() raises partway through, stop() is still called via finally."""
    from photonic_synesthesia.graph.builder import PhotonicGraph

    class _FakeGraph:
        def invoke(self, state):  # type: ignore[override]
            return state

    pg = PhotonicGraph(graph=_FakeGraph(), settings=mock.MagicMock(), nodes={})

    # Replace start and stop with mocks
    pg.start = mock.MagicMock(side_effect=RuntimeError("hardware not found"))
    pg.stop = mock.MagicMock()

    with pytest.raises(RuntimeError, match="hardware not found"):
        pg.run_loop(target_fps=1.0)

    pg.stop.assert_called(), "stop() must be called in the finally block even when start() raises"


def test_run_loop_stop_called_in_finally() -> None:
    """run_loop's finally block must call stop() even when the loop body raises."""
    from photonic_synesthesia.graph.builder import PhotonicGraph

    class _FakeGraph:
        def invoke(self, state):  # type: ignore[override]
            raise ValueError("graph error")

    pg = PhotonicGraph(graph=_FakeGraph(), settings=mock.MagicMock(), nodes={})
    pg.start = mock.MagicMock()
    pg.stop = mock.MagicMock()
    pg._running = True

    with pytest.raises(ValueError, match="graph error"):
        pg.run_loop(target_fps=1.0)

    pg.stop.assert_called()


# ---------------------------------------------------------------------------
# Feature extraction logging hygiene
# ---------------------------------------------------------------------------


def test_feature_extract_logs_missing_librosa_only_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing librosa warning should emit once per node, not once per frame."""
    from photonic_synesthesia.graph.nodes import feature_extract as feature_extract_module

    monkeypatch.setattr(feature_extract_module, "LIBROSA_AVAILABLE", False)
    warning_mock = mock.MagicMock()
    monkeypatch.setattr(feature_extract_module.logger, "warning", warning_mock)

    node = feature_extract_module.FeatureExtractNode()
    node(create_initial_state())
    node(create_initial_state())

    assert warning_mock.call_count == 1


# ---------------------------------------------------------------------------
# CLI dmx_test: cleanup in finally for non-KeyboardInterrupt exceptions
# ---------------------------------------------------------------------------


def test_dmx_test_cleanup_on_non_keyboard_interrupt() -> None:
    """dmx_test must call blackout() + stop() even if an unexpected exception occurs."""
    from click.testing import CliRunner

    from photonic_synesthesia.ui.cli import cli

    mock_node = mock.MagicMock()
    # Make start succeed but set_channel raise an unexpected error
    mock_node.start.return_value = None
    mock_node.set_channel.side_effect = RuntimeError("hardware gone")

    # Patch DMXOutputNode in its home module so the inside-function import sees the mock.
    with mock.patch(
        "photonic_synesthesia.graph.nodes.dmx_output.DMXOutputNode",
        return_value=mock_node,
    ):
        runner = CliRunner()
        runner.invoke(cli, ["dmx-test", "-c", "1", "-v", "100"])

    mock_node.blackout.assert_called()
    mock_node.stop.assert_called()


# ---------------------------------------------------------------------------
# SIGTERM handler registers on graph
# ---------------------------------------------------------------------------


def test_sigterm_handler_calls_graph_stop() -> None:
    """SIGTERM handler installed by 'run' command must call graph.stop()."""
    from click.testing import CliRunner

    from photonic_synesthesia.ui.cli import cli

    stop_calls: list[int] = []

    class _FakeGraph:
        _running = False

        def run_loop(self, target_fps: float) -> None:
            # Simulate: send SIGTERM to ourselves, then return
            signal.raise_signal(signal.SIGTERM)

        def stop(self) -> None:
            stop_calls.append(1)

        def __bool__(self) -> bool:
            return True

    # build_photonic_graph is imported inside the 'run' function body,
    # so we patch it in the graph module where it's defined.
    with mock.patch(
        "photonic_synesthesia.graph.build_photonic_graph", return_value=_FakeGraph()
    ):
        runner = CliRunner()
        runner.invoke(cli, ["run", "--mock"])

    assert len(stop_calls) >= 1, "graph.stop() must be called when SIGTERM is received"


def test_run_file_uses_audio_file_sensor_override(tmp_path: Path) -> None:
    """run-file must inject the file-backed audio sensor into the graph builder."""
    from click.testing import CliRunner

    from photonic_synesthesia.core.state import create_initial_state
    from photonic_synesthesia.graph.nodes.audio_file_sense import AudioFileSenseNode
    from photonic_synesthesia.ui.cli import cli

    audio_path = tmp_path / "fixture.wav"
    with wave.open(str(audio_path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 800)

    captured: dict[str, object] = {}

    class _FakeGraph:
        def __init__(self, audio_node: AudioFileSenseNode) -> None:
            self._running = True
            self._audio_node = audio_node

        def start(self) -> None:
            self._audio_node.start()

        def step(self):  # type: ignore[no-untyped-def]
            state = create_initial_state()
            state = self._audio_node(state)
            if self._audio_node.finished:
                self._running = False
            return state

        def stop(self) -> None:
            self._running = False
            self._audio_node.stop()

    def _fake_build(*args, **kwargs):  # type: ignore[no-untyped-def]
        captured["mock_sensors"] = kwargs["mock_sensors"]
        captured["audio_node"] = kwargs["node_overrides"]["audio_sense"]
        return _FakeGraph(captured["audio_node"])  # type: ignore[arg-type]

    with mock.patch("photonic_synesthesia.graph.build_photonic_graph", side_effect=_fake_build):
        runner = CliRunner()
        result = runner.invoke(cli, ["run-file", str(audio_path), "--offline", "--fps", "10"])

    assert result.exit_code == 0
    assert captured["mock_sensors"] is True
    assert isinstance(captured["audio_node"], AudioFileSenseNode)
    assert "No ILDA fixtures configured; falling back to in-memory preview." in result.output


def test_run_file_web_startup_failure_preserves_original_error(tmp_path: Path) -> None:
    """run-file --web must not mask startup failures with cleanup-time crashes."""
    from click.testing import CliRunner

    from photonic_synesthesia.ui.cli import cli

    audio_path = tmp_path / "fixture.wav"
    with wave.open(str(audio_path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 800)

    with mock.patch(
        "photonic_synesthesia.graph.nodes.audio_file_sense.AudioFileSenseNode.start",
        side_effect=RuntimeError("decode failed"),
    ):
        runner = CliRunner()
        result = runner.invoke(cli, ["run-file", str(audio_path), "--web"])

    assert result.exit_code == 1
    assert "decode failed" in result.output
    assert "UnboundLocalError" not in result.output


def test_run_file_applies_ether_dream_cli_overrides(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from photonic_synesthesia.core.state import create_initial_state
    from photonic_synesthesia.graph.nodes.audio_file_sense import AudioFileSenseNode
    from photonic_synesthesia.ui.cli import cli

    audio_path = tmp_path / "fixture.wav"
    with wave.open(str(audio_path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 800)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
runtime_flags:
  allow_unverified_laser_profiles: true
fixtures:
  - id: laser-main
    name: Main Laser
    type: laser
    profile: laser_aucd_cx338b_hybrid
    start_address: 1
    enabled: true
""".strip(),
        encoding="utf-8",
    )

    captured: dict[str, object] = {}

    class _FakeGraph:
        def __init__(self, audio_node: AudioFileSenseNode) -> None:
            self._running = True
            self._audio_node = audio_node

        def start(self) -> None:
            self._audio_node.start()

        def step(self):  # type: ignore[no-untyped-def]
            state = create_initial_state()
            state = self._audio_node(state)
            if self._audio_node.finished:
                self._running = False
            return state

        def stop(self) -> None:
            self._running = False
            self._audio_node.stop()

    def _fake_build(settings, *args, **kwargs):  # type: ignore[no-untyped-def]
        captured["transport_type"] = settings.ilda.transport_type
        captured["host"] = settings.ilda.ether_dream_host
        captured["port"] = settings.ilda.ether_dream_port
        return _FakeGraph(kwargs["node_overrides"]["audio_sense"])

    fake_socket = mock.MagicMock()
    fake_socket.__enter__.return_value = fake_socket
    fake_socket.__exit__.return_value = False

    with (
        mock.patch("photonic_synesthesia.graph.build_photonic_graph", side_effect=_fake_build),
        mock.patch("photonic_synesthesia.ui.cli.socket.create_connection", return_value=fake_socket),
    ):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--config",
                str(config_path),
                "run-file",
                str(audio_path),
                "--offline",
                "--fps",
                "10",
                "--ilda-transport",
                "ether_dream",
                "--ether-dream-host",
                "192.0.2.10",
                "--ether-dream-port",
                "9001",
            ],
        )

    assert result.exit_code == 0
    assert "ILDA Transport: Ether Dream 192.0.2.10:9001" in result.output
    assert captured["transport_type"] == "ether_dream"
    assert captured["host"] == "192.0.2.10"
    assert captured["port"] == 9001


def test_run_file_rejects_invalid_ether_dream_port(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from photonic_synesthesia.ui.cli import cli

    audio_path = tmp_path / "fixture.wav"
    with wave.open(str(audio_path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 800)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "run-file",
            str(audio_path),
            "--ilda-transport",
            "ether_dream",
            "--ether-dream-port",
            "70000",
        ],
    )

    assert result.exit_code == 1
    assert "--ether-dream-port must be between 1 and 65535" in result.output


def test_run_file_rejects_explicit_ild_transport_without_ilda_fixture(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from photonic_synesthesia.ui.cli import cli

    audio_path = tmp_path / "fixture.wav"
    with wave.open(str(audio_path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 800)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "run-file",
            str(audio_path),
            "--ilda-transport",
            "ild",
        ],
    )

    assert result.exit_code == 1
    assert "ILDA output requested but no enabled ILDA-primary laser fixtures are configured." in result.output
