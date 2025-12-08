"""
DMX Output Node: Thread-safe DMX transmission via Enttec Open DMX USB.

Implements the DMX512 protocol using pyftdi for the FTDI FT232R chip
in the Enttec Open DMX USB interface.
"""

from __future__ import annotations

import time
import threading
from typing import Optional
import structlog

from photonic_synesthesia.core.state import PhotonicState
from photonic_synesthesia.core.config import DMXConfig
from photonic_synesthesia.core.exceptions import DMXConnectionError, DMXTransmissionError

logger = structlog.get_logger()

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

    def __init__(self, config: DMXConfig):
        self.config = config
        self.ftdi_url = config.ftdi_url
        self.refresh_rate = config.refresh_rate_hz

        # Universe buffer (start code + 512 channels)
        self._universe = bytearray(513)
        self._universe[0] = 0x00  # Start code

        # Thread synchronization
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Serial connection
        self._serial = None

        # Stats
        self._frames_sent = 0
        self._errors = 0

    def start(self) -> None:
        """Start DMX transmission thread."""
        if not PYFTDI_AVAILABLE:
            logger.warning("pyftdi not available, DMX output disabled")
            return

        if self._running:
            return

        logger.info("Starting DMX output", url=self.ftdi_url)

        try:
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
            raise DMXConnectionError(self.ftdi_url, str(e))

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
            # Send blackout before closing
            with self._lock:
                self._universe = bytearray(513)
            time.sleep(0.05)  # Send one blackout frame

            self._serial.close()
            self._serial = None

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
        if not self._serial:
            return

        # Get current universe state
        with self._lock:
            data = bytes(self._universe)

        # Send break (hold line low)
        # The send_break method holds the line low for the specified duration
        self._serial.send_break(duration=0.0001)  # 100µs

        # Mark After Break (MAB) - short pause
        time.sleep(0.000012)  # 12µs

        # Send data (start code + 512 channels)
        self._serial.write(data)

    def __call__(self, state: PhotonicState) -> PhotonicState:
        """Apply fixture commands to DMX universe."""
        start_time = time.time()

        with self._lock:
            # Apply all fixture commands
            for cmd in state["fixture_commands"]:
                for channel, value in cmd["channel_values"].items():
                    if 1 <= channel <= 512:
                        # Clamp value to valid range
                        self._universe[channel] = max(0, min(255, value))

            # Copy to state
            state["dmx_universe"] = bytes(self._universe)

        # Clear processed commands
        state["fixture_commands"] = []

        # Record processing time
        state["processing_times"]["dmx_output"] = time.time() - start_time

        return state

    def set_channel(self, channel: int, value: int) -> None:
        """Directly set a DMX channel value."""
        if 1 <= channel <= 512:
            with self._lock:
                self._universe[channel] = max(0, min(255, value))

    def blackout(self) -> None:
        """Set all channels to zero."""
        with self._lock:
            self._universe = bytearray(513)

    def get_stats(self) -> dict:
        """Get transmission statistics."""
        return {
            "running": self._running,
            "frames_sent": self._frames_sent,
            "errors": self._errors,
            "error_rate": self._errors / max(1, self._frames_sent),
        }
