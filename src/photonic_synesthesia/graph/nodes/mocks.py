"""
Mock Nodes for Testing.

Provides mock implementations of sensor and output nodes for
testing the graph without real hardware.
"""

from __future__ import annotations

import math
import random
import time

import structlog

from photonic_synesthesia.core.state import (
    AudioFeatures,
    BeatInfo,
    CVState,
    MidiState,
    MusicStructure,
    PhotonicState,
)
from photonic_synesthesia.dmx.universe import create_universe_buffer, is_valid_dmx_channel

logger = structlog.get_logger()


class MockAudioSenseNode:
    """
    Mock audio capture that generates synthetic audio data.

    Produces a simulated waveform that can be used for testing
    the analysis pipeline.
    """

    def __init__(self, sample_rate: int = 48000) -> None:
        self.sample_rate = sample_rate
        self._time_offset = 0.0
        self._simulated_bpm = 128.0

    def start(self) -> None:
        """Mock start - does nothing."""
        logger.info("Mock audio sense started")

    def stop(self) -> None:
        """Mock stop - does nothing."""
        logger.info("Mock audio sense stopped")

    def __call__(self, state: PhotonicState) -> PhotonicState:
        """Generate synthetic audio buffer."""
        state["timestamp"] = time.time()
        state["frame_number"] += 1
        state["sample_rate"] = self.sample_rate

        # Generate synthetic audio (sine wave + noise)
        duration = 0.02  # 20ms of audio
        samples = int(self.sample_rate * duration)

        # Beat frequency
        beat_freq = self._simulated_bpm / 60.0
        t = time.time() + self._time_offset

        # Generate buffer with beat-like pulses
        buffer = []
        for i in range(samples):
            sample_t = t + i / self.sample_rate

            # Base tone
            base = 0.3 * math.sin(2 * math.pi * 100 * sample_t)

            # Beat pulse (kick drum simulation)
            beat_phase = (sample_t * beat_freq) % 1.0
            if beat_phase < 0.1:
                kick = 0.8 * math.exp(-beat_phase * 30) * math.sin(2 * math.pi * 60 * sample_t)
            else:
                kick = 0.0

            # Add some noise
            noise = 0.05 * random.uniform(-1, 1)

            buffer.append(base + kick + noise)

        state["audio_buffer"] = buffer
        state["sensor_status"]["audio"] = True

        # Also set synthetic features for faster testing
        beat_phase = (t * beat_freq) % 1.0
        energy = 0.5 + 0.3 * math.sin(beat_phase * math.pi)

        state["audio_features"] = AudioFeatures(
            rms_energy=energy,
            spectral_centroid=2000 + 1000 * math.sin(t * 0.5),
            spectral_flux=0.5 + 0.3 * math.sin(beat_phase * math.pi * 2),
            spectral_rolloff=8000,
            low_energy=0.6 + 0.3 * math.sin(beat_phase * math.pi),
            mid_energy=0.4,
            high_energy=0.2,
            mfcc_vector=[0.0] * 13,
        )

        state["beat_info"] = BeatInfo(
            bpm=self._simulated_bpm,
            beat_phase=beat_phase,
            bar_position=int((t * beat_freq / 4) % 4) + 1,
            downbeat=beat_phase < 0.1,
            confidence=0.9,
        )

        return state

    def set_bpm(self, bpm: float) -> None:
        """Set simulated BPM."""
        self._simulated_bpm = bpm


class MockMidiSenseNode:
    """Mock MIDI input for testing."""

    def __init__(self) -> None:
        self._fader_values = [1.0, 1.0, 1.0, 1.0]
        self._crossfader = 0.0

    def start(self) -> None:
        logger.info("Mock MIDI sense started")

    def stop(self) -> None:
        logger.info("Mock MIDI sense stopped")

    def __call__(self, state: PhotonicState) -> PhotonicState:
        state["midi_state"] = MidiState(
            crossfader_position=self._crossfader,
            channel_faders=self._fader_values.copy(),
            filter_positions=[0.5, 0.5, 0.5, 0.5],
            eq_positions={"hi": [0.5] * 4, "mid": [0.5] * 4, "lo": [0.5] * 4},
            active_effects=[],
            pad_triggers=[],
            last_update=time.time(),
        )
        state["sensor_status"]["midi"] = True
        return state

    def set_fader(self, channel: int, value: float) -> None:
        """Set a fader value for testing."""
        if 1 <= channel <= 4:
            self._fader_values[channel - 1] = value


class MockCVSenseNode:
    """Mock computer vision for testing."""

    def __init__(self) -> None:
        self._bpm = 128.0

    def __call__(self, state: PhotonicState) -> PhotonicState:
        state["cv_state"] = CVState(
            detected_bpm=self._bpm,
            lookahead_bass=0.5 + 0.3 * math.sin(time.time() * 0.5),
            lookahead_mids=0.4,
            lookahead_highs=0.3,
            waveform_phase=0.0,
            capture_timestamp=time.time(),
        )
        state["sensor_status"]["cv"] = True
        return state

    def set_bpm(self, bpm: float) -> None:
        """Set mock BPM."""
        self._bpm = bpm


class MockDMXOutputNode:
    """Mock DMX output for testing without hardware."""

    def __init__(self) -> None:
        self._universe: bytearray = create_universe_buffer()
        self._frames_sent = 0
        self._running = False

    def start(self) -> None:
        self._running = True
        logger.info("Mock DMX output started")

    def stop(self) -> None:
        self._running = False
        logger.info("Mock DMX output stopped", frames=self._frames_sent)

    def __call__(self, state: PhotonicState) -> PhotonicState:
        # Apply fixture commands
        for cmd in state["fixture_commands"]:
            for channel, value in cmd["channel_values"].items():
                if is_valid_dmx_channel(channel):
                    self._universe[channel] = max(0, min(255, value))

        state["dmx_universe"] = bytes(self._universe)
        state["fixture_commands"] = []
        self._frames_sent += 1

        return state

    def get_channel(self, channel: int) -> int:
        """Get current value of a channel."""
        if is_valid_dmx_channel(channel):
            return int(self._universe[channel])
        return 0

    def get_stats(self) -> dict[str, int | bool]:
        return {
            "running": self._running,
            "frames_sent": self._frames_sent,
            "errors": 0,
        }

    def blackout(self) -> None:
        self._universe = create_universe_buffer()


class StructureSimulator:
    """
    Simulates EDM track structure for testing.

    Cycles through: INTRO -> BUILDUP -> DROP -> BREAKDOWN -> BUILDUP -> DROP...
    """

    def __init__(self, cycle_time: float = 32.0) -> None:
        self.cycle_time = cycle_time
        self._start_time = time.time()

        # Structure timeline (fraction of cycle)
        self._structure_timeline: list[tuple[float, MusicStructure]] = [
            (0.0, MusicStructure.INTRO),
            (0.15, MusicStructure.VERSE),
            (0.3, MusicStructure.BUILDUP),
            (0.4, MusicStructure.DROP),
            (0.55, MusicStructure.BREAKDOWN),
            (0.7, MusicStructure.BUILDUP),
            (0.8, MusicStructure.DROP),
            (0.95, MusicStructure.OUTRO),
        ]

    def get_structure(self) -> MusicStructure:
        """Get current structure based on time."""
        elapsed = (time.time() - self._start_time) % self.cycle_time
        phase = elapsed / self.cycle_time

        current_structure = MusicStructure.UNKNOWN
        for threshold, structure in self._structure_timeline:
            if phase >= threshold:
                current_structure = structure

        return current_structure

    def reset(self) -> None:
        """Reset to beginning of cycle."""
        self._start_time = time.time()
