"""
MIDI Sense Node: Process XDJ-AZ MIDI messages for DJ intent detection.

Captures fader positions, crossfader, filter states, and pad triggers
to understand DJ intent and enable manual lighting overrides.
"""

from __future__ import annotations

import queue
import time
from typing import cast

import structlog

from photonic_synesthesia.core.config import MidiConfig
from photonic_synesthesia.core.state import MidiState, PhotonicState

logger = structlog.get_logger()

try:
    import mido

    MIDO_AVAILABLE = True
except ImportError:
    MIDO_AVAILABLE = False
    mido = None


class XDJAZMidiMap:
    """
    MIDI CC and Note mappings for XDJ-AZ.

    Note: These are approximate - verify with your unit's MIDI output.
    The XDJ-AZ uses standard Pioneer DJ MIDI conventions.
    """

    # Control Change mappings (CC number -> function)
    CROSSFADER = 0x0F  # CC 15

    # Channel faders (0-127)
    CHANNEL_FADERS = {
        1: 0x13,  # CC 19 - Channel 1
        2: 0x14,  # CC 20 - Channel 2
        3: 0x15,  # CC 21 - Channel 3
        4: 0x16,  # CC 22 - Channel 4
    }

    # Channel filters
    CHANNEL_FILTERS = {
        1: 0x17,  # CC 23
        2: 0x18,  # CC 24
        3: 0x19,  # CC 25
        4: 0x1A,  # CC 26
    }

    # EQ (hi/mid/lo per channel)
    EQ_HI = {1: 0x07, 2: 0x0B, 3: 0x47, 4: 0x4B}
    EQ_MID = {1: 0x08, 2: 0x0C, 3: 0x48, 4: 0x4C}
    EQ_LO = {1: 0x09, 2: 0x0D, 3: 0x49, 4: 0x4D}

    # Performance pad note ranges (Note On)
    PAD_NOTES_CH1 = range(0x30, 0x38)  # Notes 48-55
    PAD_NOTES_CH2 = range(0x38, 0x40)  # Notes 56-63


class MidiSenseNode:
    """
    Processes MIDI input from XDJ-AZ.

    Uses mido with callback interface for real-time MIDI capture.
    Messages are queued and processed during graph execution.
    """

    def __init__(self, config: MidiConfig):
        self.config = config
        self.midi_map = XDJAZMidiMap()

        # Thread-safe queue for MIDI messages
        self._message_queue: queue.Queue = queue.Queue(maxsize=1000)

        # MIDI port handle
        self._port = None
        self._running = False

        # Current state cache
        self._fader_values: dict[int, float] = {1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0}
        self._filter_values: dict[int, float] = {1: 0.5, 2: 0.5, 3: 0.5, 4: 0.5}
        self._eq_values: dict[str, dict[int, float]] = {
            "hi": {1: 0.5, 2: 0.5, 3: 0.5, 4: 0.5},
            "mid": {1: 0.5, 2: 0.5, 3: 0.5, 4: 0.5},
            "lo": {1: 0.5, 2: 0.5, 3: 0.5, 4: 0.5},
        }
        self._crossfader: float = 0.0
        self._recent_pads: list[int] = []

    def _find_port(self) -> str | None:
        """Find XDJ-AZ MIDI port by name pattern."""
        if not MIDO_AVAILABLE:
            return None

        available = cast(list[str], mido.get_input_names())
        logger.debug("Available MIDI ports", ports=available)

        # Try explicit port name first
        if self.config.port_name and self.config.port_name in available:
            return self.config.port_name

        # Search for matching pattern
        for pattern in self.config.auto_detect_patterns:
            for port in available:
                if pattern.lower() in port.lower():
                    return port

        return None

    def _on_message(self, msg: mido.Message) -> None:
        """Callback for incoming MIDI messages."""
        try:
            self._message_queue.put_nowait(msg)
        except queue.Full:
            logger.warning("MIDI queue full, dropping message")

    def start(self) -> None:
        """Start MIDI input capture."""
        if not MIDO_AVAILABLE:
            logger.warning("mido not available, MIDI disabled")
            return

        port_name = self._find_port()
        if not port_name:
            logger.warning("XDJ-AZ MIDI port not found")
            return

        try:
            self._port = mido.open_input(port_name, callback=self._on_message)
            self._running = True
            logger.info("MIDI input started", port=port_name)
        except Exception as e:
            logger.error("Failed to open MIDI port", error=str(e))

    def stop(self) -> None:
        """Stop MIDI input capture."""
        if self._port:
            self._port.close()
            self._port = None
        self._running = False
        logger.info("MIDI input stopped")

    def __call__(self, state: PhotonicState) -> PhotonicState:
        """Process queued MIDI messages and update state."""
        start_time = time.time()
        current_time = state["timestamp"]

        # Process all queued messages
        messages_processed = 0
        while not self._message_queue.empty():
            try:
                msg = self._message_queue.get_nowait()
                self._process_message(msg)
                messages_processed += 1
            except queue.Empty:
                break

        # Build state update
        active_effects = self._infer_active_effects()
        state["midi_state"] = MidiState(
            crossfader_position=self._crossfader,
            channel_faders=list(self._fader_values.values()),
            filter_positions=list(self._filter_values.values()),
            eq_positions={
                "hi": [self._eq_values["hi"][1], self._eq_values["hi"][2], self._eq_values["hi"][3], self._eq_values["hi"][4]],
                "mid": [self._eq_values["mid"][1], self._eq_values["mid"][2], self._eq_values["mid"][3], self._eq_values["mid"][4]],
                "lo": [self._eq_values["lo"][1], self._eq_values["lo"][2], self._eq_values["lo"][3], self._eq_values["lo"][4]],
            },
            active_effects=active_effects,
            pad_triggers=self._recent_pads.copy(),
            last_update=current_time,
        )

        # Clear pad triggers after reading
        self._recent_pads.clear()

        # Update sensor status
        state["sensor_status"]["midi"] = self._running

        # Record processing time
        state["processing_times"]["midi_sense"] = time.time() - start_time

        return state

    def _process_message(self, msg: mido.Message) -> None:
        """Process a single MIDI message."""
        if msg.type == "control_change":
            self._handle_cc(msg.control, msg.value)
        elif msg.type == "note_on" and msg.velocity > 0:
            self._handle_note_on(msg.note, msg.velocity)

    def _handle_cc(self, cc: int, value: int) -> None:
        """Handle Control Change message."""
        normalized = value / 127.0

        # Crossfader
        if cc == self.midi_map.CROSSFADER:
            self._crossfader = (normalized * 2) - 1  # -1 to 1
            return

        # Channel faders
        for ch, fader_cc in self.midi_map.CHANNEL_FADERS.items():
            if cc == fader_cc:
                self._fader_values[ch] = normalized
                return

        # Filters
        for ch, filter_cc in self.midi_map.CHANNEL_FILTERS.items():
            if cc == filter_cc:
                self._filter_values[ch] = normalized
                return

        # EQ knobs
        for ch, eq_cc in self.midi_map.EQ_HI.items():
            if cc == eq_cc:
                self._eq_values["hi"][ch] = normalized
                return
        for ch, eq_cc in self.midi_map.EQ_MID.items():
            if cc == eq_cc:
                self._eq_values["mid"][ch] = normalized
                return
        for ch, eq_cc in self.midi_map.EQ_LO.items():
            if cc == eq_cc:
                self._eq_values["lo"][ch] = normalized
                return

    def _handle_note_on(self, note: int, velocity: int) -> None:
        """Handle Note On message (pad triggers)."""
        # Check if it's a performance pad
        if note in self.midi_map.PAD_NOTES_CH1 or note in self.midi_map.PAD_NOTES_CH2:
            self._recent_pads.append(note)
            logger.debug("Pad triggered", note=note, velocity=velocity)

    def _infer_active_effects(self) -> list[str]:
        """Infer coarse FX intents from current control positions."""
        effects: set[str] = set()
        avg_filter = sum(self._filter_values.values()) / max(1, len(self._filter_values))
        if avg_filter > 0.7:
            effects.add("high_pass_sweep")
        elif avg_filter < 0.3:
            effects.add("low_pass_sweep")

        if any(value > 0.9 for value in self._eq_values["hi"].values()):
            effects.add("hi_boost")
        if any(value < 0.1 for value in self._eq_values["lo"].values()):
            effects.add("bass_cut")

        return sorted(effects)
