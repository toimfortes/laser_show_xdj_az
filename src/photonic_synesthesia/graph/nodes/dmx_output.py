"""
DMX Output Node: Thread-safe DMX transmission via Enttec Open DMX USB.

Implements the DMX512 protocol using pyftdi for the FTDI FT232R chip
in the Enttec Open DMX USB interface.
"""

from __future__ import annotations

import math
import threading
import time

from photonic_synesthesia.core.config import DMXConfig
from photonic_synesthesia.core.exceptions import DMXConnectionError
from photonic_synesthesia.core.state import FixtureCommand, PhotonicState
from photonic_synesthesia.dmx.artnet import ArtNetTransmitter
from photonic_synesthesia.dmx.universe import (
    create_universe_buffer,
    extract_channel_payload,
    is_valid_dmx_channel,
)

try:
    import structlog

    logger = structlog.get_logger()
except ImportError:  # pragma: no cover - fallback for minimal test envs
    import logging

    logger = logging.getLogger(__name__)

try:
    from pyftdi.serialext import serial_for_url

    PYFTDI_AVAILABLE = True
except ImportError:
    PYFTDI_AVAILABLE = False
    serial_for_url = None


class DMXOutputNode:
    """
    Transmits DMX512 frames via Enttec Open DMX USB.

    The Enttec Open DMX USB uses an FTDI FT232R chip and requires
    the host to generate DMX timing (break, MAB, data). This is
    handled by a dedicated transmission thread.

    DMX512 Protocol:
    - Break: Line held low for >88µs (we use ~100µs)
    - Mark After Break (MAB): Line high for >8µs (we use ~12µs)
    - Start code: 0x00
    - 512 bytes of channel data
    - Transmitted at 250 kbaud (4µs per bit)
    """

    def __init__(self, config: DMXConfig, dmx_double_buffer: bool = True):
        self.config = config
        self.ftdi_url = config.ftdi_url
        self.refresh_rate = config.refresh_rate_hz
        self.dmx_double_buffer = dmx_double_buffer

        # Universe buffer (start code + 512 channels)
        self._universe = create_universe_buffer()
        self._blackout_requested = threading.Event()

        # Thread synchronization
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None

        # Serial connection
        self._serial = None
        self._artnet: ArtNetTransmitter | None = None
        self._artnet_sequence: int = 0

        # Stats
        self._frames_sent = 0
        self._errors = 0

    def start(self) -> None:
        """Start DMX transmission thread."""
        if self.config.interface_type != "artnet" and not PYFTDI_AVAILABLE:
            logger.warning("pyftdi not available, DMX output disabled")
            return

        if self._running:
            return

        logger.info("Starting DMX output", interface=self.config.interface_type)

        try:
            if self.config.interface_type == "artnet":
                self._artnet = ArtNetTransmitter(
                    host=self.config.artnet_host,
                    port=self.config.artnet_port,
                    broadcast=self.config.artnet_broadcast,
                )
                self._artnet.open()
                logger.info(
                    "Art-Net output ready",
                    host=self.config.artnet_host,
                    port=self.config.artnet_port,
                )
            else:
                # Open FTDI serial connection
                # DMX uses 250kbaud, 8N2 (2 stop bits)
                self._serial = serial_for_url(
                    self.ftdi_url,
                    baudrate=250000,
                    bytesize=8,
                    stopbits=2,
                )
                logger.info("DMX serial opened")

        except Exception as e:
            target = (
                f"{self.config.artnet_host}:{self.config.artnet_port}"
                if self.config.interface_type == "artnet"
                else self.ftdi_url
            )
            raise DMXConnectionError(target, str(e)) from e

        # Start transmission thread
        self._running = True
        self._thread = threading.Thread(
            target=self._transmit_loop,
            name="DMX-Transmit",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop DMX transmission."""
        self._running = False

        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

        if self._serial:
            # Transmit thread is stopped; send one blackout frame directly.
            blackout = bytes(create_universe_buffer())
            try:
                self._serial.send_break(duration=0.0001)
                time.sleep(0.000012)
                self._serial.write(blackout)
            except Exception:
                pass
            self._serial.close()
            self._serial = None

        if self._artnet:
            # Transmit thread is stopped; send one blackout packet directly.
            blackout_data = bytes(512)
            try:
                self._artnet.send_dmx(
                    universe=self._artnet_universe_address(),
                    dmx_data=blackout_data,
                    sequence=self._artnet_sequence,
                )
            except Exception:
                pass
            self._artnet.close()
            self._artnet = None

        logger.info(
            "DMX output stopped",
            frames_sent=self._frames_sent,
            errors=self._errors,
        )

    def _transmit_loop(self) -> None:
        """
        Continuous DMX frame transmission loop.

        Runs in a dedicated thread at the configured refresh rate.
        """
        frame_time = 1.0 / self.refresh_rate

        while self._running:
            start = time.time()

            try:
                self._send_frame()
                self._frames_sent += 1
            except Exception as e:
                self._errors += 1
                if self._errors % 100 == 1:
                    logger.error("DMX transmission error", error=str(e))

            # Maintain frame rate
            elapsed = time.time() - start
            sleep_time = frame_time - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _send_frame(self) -> None:
        """Send a single DMX512 frame."""
        if self._blackout_requested.is_set():
            data = bytes(create_universe_buffer())
        else:
            # Get current universe state
            with self._lock:
                data = bytes(self._universe)

        if self.config.interface_type == "artnet":
            if not self._artnet:
                return
            # ArtDMX data excludes DMX start code.
            universe_data = extract_channel_payload(data)
            self._artnet.send_dmx(
                universe=self._artnet_universe_address(),
                dmx_data=universe_data,
                sequence=self._artnet_sequence,
            )
            self._artnet_sequence = (self._artnet_sequence + 1) % 256
            return

        if not self._serial:
            return

        # Send break (hold line low)
        # The send_break method holds the line low for the specified duration
        self._serial.send_break(duration=0.0001)  # 100µs

        # Mark After Break (MAB) - short pause
        time.sleep(0.000012)  # 12µs

        # Send data (start code + 512 channels)
        self._serial.write(data)

    def _artnet_universe_address(self) -> int:
        """
        Build Art-Net Port-Address field.

        Bits:
        - 0..3  universe
        - 4..7  subnet
        - 8..14 net
        """
        return (
            ((self.config.artnet_net & 0x7F) << 8)
            | ((self.config.artnet_subnet & 0x0F) << 4)
            | (self.config.universe & 0x0F)
        )

    def __call__(self, state: PhotonicState) -> PhotonicState:
        """Apply fixture commands to DMX universe."""
        start_time = time.time()
        if self._blackout_requested.is_set():
            blackout = create_universe_buffer()
            with self._lock:
                self._universe = blackout
            state["dmx_universe"] = bytes(blackout)
        elif self.dmx_double_buffer:
            with self._lock:
                next_universe = bytearray(self._universe)
            self._apply_fixture_commands(next_universe, state["fixture_commands"])
            with self._lock:
                self._universe = next_universe
                state["dmx_universe"] = bytes(self._universe)
        else:
            with self._lock:
                self._apply_fixture_commands(self._universe, state["fixture_commands"])
                state["dmx_universe"] = bytes(self._universe)

        # Clear processed commands
        state["fixture_commands"] = []

        # Record processing time
        state["processing_times"]["dmx_output"] = time.time() - start_time

        return state

    def set_channel(self, channel: int, value: int) -> None:
        """Directly set a DMX channel value."""
        if is_valid_dmx_channel(channel):
            with self._lock:
                self._universe[channel] = max(0, min(255, value))
            self._blackout_requested.clear()

    def request_blackout(self) -> None:
        """
        Asynchronously request blackout without blocking on the universe lock.

        The TX thread checks this latch before every frame send.
        """
        self._blackout_requested.set()

    def blackout(self) -> None:
        """Set all channels to zero."""
        with self._lock:
            self._universe = create_universe_buffer()
        self._blackout_requested.set()

    def get_stats(self) -> dict:
        """Get transmission statistics."""
        return {
            "running": self._running,
            "frames_sent": self._frames_sent,
            "errors": self._errors,
            "error_rate": self._errors / max(1, self._frames_sent),
            "blackout_requested": self._blackout_requested.is_set(),
            "dmx_double_buffer": self.dmx_double_buffer,
        }

    @staticmethod
    def _apply_fixture_commands(universe: bytearray, commands: list[FixtureCommand]) -> None:
        """Apply fixture command values into a mutable universe buffer."""
        for cmd in commands:
            for channel, value in cmd["channel_values"].items():
                if not is_valid_dmx_channel(channel):
                    continue
                fval = float(value)
                if not math.isfinite(fval):
                    # Reject NaN/Inf silently – never write garbage to hardware.
                    continue
                universe[channel] = max(0, min(255, int(fval)))
