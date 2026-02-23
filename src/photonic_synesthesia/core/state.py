"""
LangGraph State Definitions for Photonic Synesthesia.

This module defines the central state object that flows through the LangGraph
state machine, containing all sensor data, analysis results, and control signals.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TypedDict

import numpy as np

from photonic_synesthesia.dmx.universe import create_universe_buffer


class MusicStructure(Enum):
    """Musical structure classification for scene selection."""

    INTRO = "intro"
    VERSE = "verse"
    BUILDUP = "buildup"
    DROP = "drop"
    BREAKDOWN = "breakdown"
    OUTRO = "outro"
    UNKNOWN = "unknown"


class FixtureCommand(TypedDict):
    """Command to update a specific fixture's DMX channels."""

    fixture_id: str
    fixture_type: str  # "laser", "moving_head", "panel"
    channel_values: dict[int, int]  # channel_offset -> value (0-255)


class AudioFeatures(TypedDict):
    """Extracted audio features from spectral analysis."""

    rms_energy: float
    spectral_centroid: float
    spectral_flux: float
    spectral_rolloff: float
    low_energy: float  # 20-200 Hz
    mid_energy: float  # 200-2000 Hz
    high_energy: float  # 2000+ Hz
    mfcc_vector: list[float]


class BeatInfo(TypedDict):
    """Beat tracking information."""

    bpm: float
    beat_phase: float  # 0.0 - 1.0 within current beat
    bar_position: int  # 1-4 within bar
    downbeat: bool  # True if on the "1"
    confidence: float  # 0.0 - 1.0


class MidiState(TypedDict):
    """State derived from XDJ-AZ MIDI messages."""

    crossfader_position: float  # -1.0 (left) to 1.0 (right)
    channel_faders: list[float]  # 4 channels, 0.0 - 1.0
    filter_positions: list[float]  # HPF/LPF positions per channel
    eq_positions: dict[str, list[float]]  # hi/mid/lo per channel
    active_effects: list[str]
    pad_triggers: list[int]  # Recently triggered pad numbers
    last_update: float  # Timestamp


class CVState(TypedDict):
    """State derived from computer vision / screen reading."""

    detected_bpm: float | None
    lookahead_bass: float  # Predicted bass intensity (0-1)
    lookahead_mids: float  # Predicted mid intensity (0-1)
    lookahead_highs: float  # Predicted high intensity (0-1)
    waveform_phase: float  # Position in waveform view
    capture_timestamp: float


class RuleStreamState(TypedDict):
    """Low-latency stream for beat-accurate modulation."""

    low_band: float
    mid_band: float
    high_band: float
    transient: float
    beat_pulse: float


class MLStreamState(TypedDict):
    """Higher-latency stream for scene/mood guidance."""

    predicted_scene: str
    confidence: float
    horizon_ms: int


class DirectorState(TypedDict):
    """Director-level intent before fixture interpretation."""

    target_scene: str
    energy_level: float
    color_theme: str
    movement_style: str
    strobe_budget_hz: float
    allow_scene_transition: bool


class SceneState(TypedDict):
    """Current scene and transition state."""

    current_scene: str
    pending_scene: str | None
    transition_progress: float  # 0.0 - 1.0
    transition_start_time: float
    scene_start_time: float


class SafetyState(TypedDict):
    """Safety system status."""

    ok: bool
    last_heartbeat: float
    error_state: str | None
    laser_enabled: bool
    strobe_enabled: bool
    emergency_stop: bool


class PhotonicState(TypedDict):
    """
    Central state object flowing through LangGraph.

    This TypedDict contains all sensor data, analysis results, and control
    signals used by the photonic synesthesia system. It is passed between
    nodes in the LangGraph state machine and updated incrementally.
    """

    # Timing & Synchronization
    timestamp: float  # Current time
    frame_number: int  # Processing frame counter

    # Raw Audio Buffer (for analysis nodes)
    audio_buffer: list[float]  # Recent audio samples
    sample_rate: int  # Audio sample rate (typically 48000)

    # Extracted Audio Features
    audio_features: AudioFeatures

    # Beat Tracking
    beat_info: BeatInfo

    # Structure Detection
    current_structure: MusicStructure
    structure_confidence: float
    drop_probability: float  # Imminent drop likelihood (0-1)
    time_since_last_drop: float  # Seconds
    time_since_structure_change: float

    # MIDI Intent (from XDJ-AZ)
    midi_state: MidiState

    # Computer Vision (from Rekordbox screen)
    cv_state: CVState

    # Fused BPM (combining audio + CV)
    fused_bpm: float
    bpm_source: str  # "audio", "cv", "fused"

    # Dual-stream analysis (rule + ML)
    rule_stream: RuleStreamState
    ml_stream: MLStreamState

    # Director output intent
    director_state: DirectorState

    # Scene Management
    scene_state: SceneState

    # Fixture Commands (output)
    fixture_commands: list[FixtureCommand]

    # DMX Universe Buffer
    dmx_universe: bytes  # Start code + 512 channel slots

    # Safety Status
    safety_state: SafetyState

    # System Health
    sensor_status: dict[str, bool]  # Which sensors are active
    processing_times: dict[str, float]  # Node timing for profiling


def create_initial_state() -> PhotonicState:
    """Create a fresh PhotonicState with default values."""
    now = time.time()

    return PhotonicState(
        # Timing
        timestamp=now,
        frame_number=0,
        # Audio
        audio_buffer=[],
        sample_rate=48000,
        audio_features=AudioFeatures(
            rms_energy=0.0,
            spectral_centroid=0.0,
            spectral_flux=0.0,
            spectral_rolloff=0.0,
            low_energy=0.0,
            mid_energy=0.0,
            high_energy=0.0,
            mfcc_vector=[0.0] * 13,
        ),
        # Beat
        beat_info=BeatInfo(
            bpm=128.0,  # Default EDM tempo
            beat_phase=0.0,
            bar_position=1,
            downbeat=False,
            confidence=0.0,
        ),
        # Structure
        current_structure=MusicStructure.UNKNOWN,
        structure_confidence=0.0,
        drop_probability=0.0,
        time_since_last_drop=float("inf"),
        time_since_structure_change=0.0,
        # MIDI
        midi_state=MidiState(
            crossfader_position=0.0,
            channel_faders=[1.0, 1.0, 1.0, 1.0],
            filter_positions=[0.5, 0.5, 0.5, 0.5],
            eq_positions={"hi": [0.5] * 4, "mid": [0.5] * 4, "lo": [0.5] * 4},
            active_effects=[],
            pad_triggers=[],
            last_update=now,
        ),
        # CV
        cv_state=CVState(
            detected_bpm=None,
            lookahead_bass=0.5,
            lookahead_mids=0.5,
            lookahead_highs=0.5,
            waveform_phase=0.0,
            capture_timestamp=now,
        ),
        # Fused BPM
        fused_bpm=128.0,
        bpm_source="default",
        # Dual-stream analysis
        rule_stream=RuleStreamState(
            low_band=0.0,
            mid_band=0.0,
            high_band=0.0,
            transient=0.0,
            beat_pulse=0.0,
        ),
        ml_stream=MLStreamState(
            predicted_scene="idle",
            confidence=0.0,
            horizon_ms=250,
        ),
        # Director intent
        director_state=DirectorState(
            target_scene="idle",
            energy_level=0.0,
            color_theme="neutral",
            movement_style="steady",
            strobe_budget_hz=0.0,
            allow_scene_transition=True,
        ),
        # Scene
        scene_state=SceneState(
            current_scene="idle",
            pending_scene=None,
            transition_progress=0.0,
            transition_start_time=now,
            scene_start_time=now,
        ),
        # Fixture output
        fixture_commands=[],
        dmx_universe=bytes(create_universe_buffer()),  # Start code + 512 channels
        # Safety
        safety_state=SafetyState(
            ok=True,
            last_heartbeat=now,
            error_state=None,
            laser_enabled=True,
            strobe_enabled=True,
            emergency_stop=False,
        ),
        # System
        sensor_status={
            "audio": False,
            "midi": False,
            "cv": False,
            "prodjlink": False,
            "ml": False,
        },
        processing_times={},
    )


@dataclass
class StateHistory:
    """
    Maintains a rolling history of state for temporal analysis.

    Used for structure detection (detecting trends over time) and
    for graceful degradation (using historical data when sensors fail).
    """

    max_history: int = 500  # ~10 seconds at 50Hz

    rms_history: list[float] = field(default_factory=list)
    spectral_centroid_history: list[float] = field(default_factory=list)
    bpm_history: list[float] = field(default_factory=list)
    structure_history: list[MusicStructure] = field(default_factory=list)
    timestamps: list[float] = field(default_factory=list)

    def append(self, state: PhotonicState) -> None:
        """Add current state to history, maintaining max size."""
        self.rms_history.append(state["audio_features"]["rms_energy"])
        self.spectral_centroid_history.append(state["audio_features"]["spectral_centroid"])
        self.bpm_history.append(state["beat_info"]["bpm"])
        self.structure_history.append(state["current_structure"])
        self.timestamps.append(state["timestamp"])

        # Trim to max size
        if len(self.timestamps) > self.max_history:
            self.rms_history = self.rms_history[-self.max_history :]
            self.spectral_centroid_history = self.spectral_centroid_history[-self.max_history :]
            self.bpm_history = self.bpm_history[-self.max_history :]
            self.structure_history = self.structure_history[-self.max_history :]
            self.timestamps = self.timestamps[-self.max_history :]

    def get_rms_trend(self, window: int = 100) -> float:
        """Calculate RMS slope over recent window (positive = rising)."""
        if len(self.rms_history) < window:
            return 0.0
        recent = self.rms_history[-window:]
        coeffs = np.polyfit(range(len(recent)), recent, 1)
        return float(coeffs[0])

    def get_average_bpm(self, window: int = 50) -> float:
        """Get average BPM over recent window."""
        if not self.bpm_history:
            return 128.0
        recent = self.bpm_history[-window:]
        return float(np.mean(recent))
