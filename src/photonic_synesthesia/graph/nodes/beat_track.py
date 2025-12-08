"""
Beat Tracking Node: Real-time beat and tempo detection.

Supports multiple backends:
- BeatNet: State-of-the-art CRNN + particle filtering (recommended)
- madmom: RNN-based beat tracking with DBN inference
"""

from __future__ import annotations

import time
from typing import Optional
from collections import deque
import numpy as np
import structlog

from photonic_synesthesia.core.state import PhotonicState, BeatInfo
from photonic_synesthesia.core.config import BeatTrackingConfig

logger = structlog.get_logger()

# Try importing beat tracking backends
BEATNET_AVAILABLE = False
MADMOM_AVAILABLE = False

try:
    from BeatNet.BeatNet import BeatNet
    BEATNET_AVAILABLE = True
except ImportError:
    pass

try:
    import madmom
    from madmom.features.beats import RNNBeatProcessor, DBNBeatTrackingProcessor
    MADMOM_AVAILABLE = True
except ImportError:
    pass


class BeatTrackNode:
    """
    Real-time beat tracking using neural network models.

    Provides BPM estimation, beat phase (position within current beat),
    bar position (1-4), and confidence score.
    """

    def __init__(self, config: BeatTrackingConfig):
        self.config = config
        self.backend = config.backend

        # Beat history for tempo smoothing
        self._beat_times: deque = deque(maxlen=32)
        self._last_beat_time: float = 0.0
        self._current_bpm: float = 128.0  # Default EDM tempo
        self._bar_position: int = 1

        # Initialize backend
        self._processor = None
        self._initialize_backend()

    def _initialize_backend(self) -> None:
        """Initialize the selected beat tracking backend."""
        if self.backend == "beatnet" and BEATNET_AVAILABLE:
            logger.info("Initializing BeatNet backend")
            try:
                self._processor = BeatNet(
                    1,  # Mode 1: streaming
                    mode='online',
                    inference_model='PF',  # Particle filtering
                    plot=[],
                    thread=False,
                )
                return
            except Exception as e:
                logger.warning(f"BeatNet init failed: {e}, falling back to madmom")

        if MADMOM_AVAILABLE:
            logger.info("Initializing madmom backend")
            try:
                # Use online mode RNN processor
                from madmom.models import BEATS_LSTM
                self._processor = RNNBeatProcessor(
                    online=True,
                    nn_files=[BEATS_LSTM[0]],  # Single model for speed
                )
                return
            except Exception as e:
                logger.warning(f"madmom init failed: {e}")

        logger.warning("No beat tracking backend available, using fallback")
        self._processor = None

    def __call__(self, state: PhotonicState) -> PhotonicState:
        """Detect beats and update state."""
        start_time = time.time()
        current_time = state["timestamp"]

        if self._processor is None:
            # Fallback: estimate from current BPM
            return self._fallback_beat_tracking(state, current_time)

        audio_buffer = state.get("audio_buffer", [])
        if len(audio_buffer) < 1024:
            return state

        try:
            # Process audio through beat detector
            y = np.array(audio_buffer[-4096:], dtype=np.float32)  # Last ~85ms at 48kHz

            if BEATNET_AVAILABLE and hasattr(self._processor, 'process'):
                # BeatNet returns (beat_time, downbeat_flag) or None
                result = self._processor.process(y)
                if result is not None:
                    beat_time, is_downbeat = result
                    self._on_beat_detected(current_time, is_downbeat)

            elif MADMOM_AVAILABLE and hasattr(self._processor, '__call__'):
                # madmom returns beat activation function
                activation = self._processor(y)
                if len(activation) > 0 and np.max(activation) > self.config.confidence_threshold:
                    # Beat detected
                    self._on_beat_detected(current_time, downbeat=False)

        except Exception as e:
            logger.error("Beat tracking failed", error=str(e))

        # Update state with current beat info
        state["beat_info"] = self._compute_beat_info(current_time)

        # Record processing time
        state["processing_times"]["beat_track"] = time.time() - start_time

        return state

    def _on_beat_detected(self, current_time: float, downbeat: bool = False) -> None:
        """Handle a detected beat."""
        self._beat_times.append(current_time)
        self._last_beat_time = current_time

        # Update bar position
        if downbeat:
            self._bar_position = 1
        else:
            self._bar_position = (self._bar_position % 4) + 1

        # Recalculate BPM from beat history
        if len(self._beat_times) >= 4:
            intervals = np.diff(list(self._beat_times)[-8:])
            if len(intervals) > 0:
                avg_interval = np.median(intervals)
                if 0.2 < avg_interval < 2.0:  # Sanity check: 30-300 BPM
                    self._current_bpm = 60.0 / avg_interval

    def _compute_beat_info(self, current_time: float) -> BeatInfo:
        """Compute current beat state."""
        # Calculate beat phase (0.0 - 1.0)
        beat_duration = 60.0 / self._current_bpm
        time_since_beat = current_time - self._last_beat_time
        beat_phase = (time_since_beat % beat_duration) / beat_duration

        # Confidence based on recency of beat detection
        time_since_last = current_time - self._last_beat_time
        confidence = max(0.0, 1.0 - (time_since_last / 2.0))  # Decay over 2 seconds

        return BeatInfo(
            bpm=self._current_bpm,
            beat_phase=beat_phase,
            bar_position=self._bar_position,
            downbeat=(self._bar_position == 1),
            confidence=confidence,
        )

    def _fallback_beat_tracking(
        self, state: PhotonicState, current_time: float
    ) -> PhotonicState:
        """Fallback beat tracking using assumed BPM."""
        # Use RMS peaks as rough beat indicator
        rms = state["audio_features"]["rms_energy"]

        # Simple peak detection
        if not hasattr(self, '_rms_history'):
            self._rms_history = deque(maxlen=50)

        self._rms_history.append(rms)

        if len(self._rms_history) >= 10:
            recent_avg = np.mean(list(self._rms_history)[-10:])
            if rms > recent_avg * 1.5:  # Peak detected
                self._on_beat_detected(current_time)

        state["beat_info"] = self._compute_beat_info(current_time)
        return state
