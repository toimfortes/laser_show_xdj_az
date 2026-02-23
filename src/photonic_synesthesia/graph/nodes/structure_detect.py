"""
Structure Detection Node: Detect musical structure (drop, buildup, breakdown).

Uses heuristics based on audio features to classify the current
musical section and predict imminent drops.
"""

from __future__ import annotations

import time
from collections import deque
from typing import cast

import numpy as np
import structlog

from photonic_synesthesia.core.config import StructureDetectionConfig
from photonic_synesthesia.core.state import MusicStructure, PhotonicState

logger = structlog.get_logger()


class StructureDetectNode:
    """
    Detects musical structure transitions using audio feature analysis.

    Classifies current section as:
    - INTRO: Low energy, gradual build
    - VERSE: Medium energy, rhythmic
    - BUILDUP: Rising energy, increasing brightness
    - DROP: High energy spike after gap, bass-dominated
    - BREAKDOWN: Low energy, reduced drums
    - OUTRO: Declining energy

    Also predicts probability of imminent drop.
    """

    def __init__(self, config: StructureDetectionConfig):
        self.config = config

        # History buffers
        self._rms_history: deque = deque(maxlen=500)  # ~10s at 50Hz
        self._centroid_history: deque = deque(maxlen=500)
        self._low_energy_history: deque = deque(maxlen=500)

        # State tracking
        self._current_structure = MusicStructure.UNKNOWN
        self._structure_start_time: float = 0.0
        self._last_drop_time: float = 0.0
        self._in_gap: bool = False
        self._gap_start_time: float = 0.0
        self._pre_gap_rms: float = 0.0

    def __call__(self, state: PhotonicState) -> PhotonicState:
        """Detect current musical structure and update state."""
        start_time = time.time()
        current_time = state["timestamp"]

        # Get current features
        features = state["audio_features"]
        rms = features["rms_energy"]
        centroid = features["spectral_centroid"]
        low_energy = features["low_energy"]

        # Update history
        self._rms_history.append(rms)
        self._centroid_history.append(centroid)
        self._low_energy_history.append(low_energy)

        # Detect structure
        new_structure, drop_prob = self._detect_structure(rms, centroid, low_energy, current_time)

        # Update state
        if new_structure != self._current_structure:
            logger.info(
                "Structure change",
                old=self._current_structure.value,
                new=new_structure.value,
            )
            self._current_structure = new_structure
            self._structure_start_time = current_time

        state["current_structure"] = self._current_structure
        state["structure_confidence"] = self._calculate_confidence()
        state["drop_probability"] = drop_prob
        state["time_since_last_drop"] = current_time - self._last_drop_time
        state["time_since_structure_change"] = current_time - self._structure_start_time

        # Record processing time
        state["processing_times"]["structure_detect"] = time.time() - start_time

        return state

    def _detect_structure(
        self,
        rms: float,
        centroid: float,
        low_energy: float,
        current_time: float,
    ) -> tuple[MusicStructure, float]:
        """
        Detect current structure based on features.

        Returns (structure, drop_probability).
        """
        if len(self._rms_history) < 50:
            return MusicStructure.UNKNOWN, 0.0

        # Calculate derived metrics
        rms_history = list(self._rms_history)
        long_term_avg = np.mean(rms_history)
        short_term_avg = np.mean(rms_history[-50:])  # Last 1 second
        rms_slope = self._calculate_slope(rms_history[-100:])  # Last 2 seconds

        # Centroid trend (brightness)
        centroid_history = list(self._centroid_history)
        centroid_avg = np.mean(centroid_history) if centroid_history else 0

        # Drop probability
        drop_prob = 0.0

        # =================================================================
        # Gap Detection (pre-drop silence)
        # =================================================================
        gap_threshold = long_term_avg * self.config.gap_rms_threshold

        if not self._in_gap and rms < gap_threshold and short_term_avg > gap_threshold * 0.5:
            # Entering a gap - energy suddenly dropped
            self._in_gap = True
            self._gap_start_time = current_time
            self._pre_gap_rms = short_term_avg
            logger.debug("Entering gap", rms=rms, threshold=gap_threshold)

        if self._in_gap:
            gap_duration = current_time - self._gap_start_time

            if gap_duration < 1.0:
                # We're in the gap - high drop probability
                drop_prob = 0.8 + (gap_duration * 0.15)  # Increases during gap
            elif rms > self._pre_gap_rms * 0.5:
                # Gap ended - check if this is a drop
                self._in_gap = False
                if rms > long_term_avg * self.config.drop_rms_multiplier:
                    if current_time - self._last_drop_time > self.config.min_drop_interval_s:
                        self._last_drop_time = current_time
                        return MusicStructure.DROP, 0.0
            elif gap_duration > 2.0:
                # Gap too long, probably a breakdown
                self._in_gap = False

        # =================================================================
        # Drop Detection (without gap)
        # =================================================================
        if (
            rms > long_term_avg * self.config.drop_rms_multiplier
            and low_energy > np.mean(list(self._low_energy_history)) * 1.5
            and current_time - self._last_drop_time > self.config.min_drop_interval_s
        ):
            self._last_drop_time = current_time
            return MusicStructure.DROP, 0.0

        # =================================================================
        # Buildup Detection
        # =================================================================
        if rms_slope > self.config.buildup_slope_threshold:
            if centroid > centroid_avg * 1.2:  # Rising brightness
                drop_prob = min(1.0, rms_slope * 20)
                return MusicStructure.BUILDUP, drop_prob

        # =================================================================
        # Breakdown Detection
        # =================================================================
        if low_energy < np.mean(list(self._low_energy_history)) * 0.3:
            # Bass has dropped out
            return MusicStructure.BREAKDOWN, 0.0

        # =================================================================
        # Verse/Normal
        # =================================================================
        if short_term_avg > long_term_avg * 0.7:
            return MusicStructure.VERSE, drop_prob

        # =================================================================
        # Intro/Outro
        # =================================================================
        if short_term_avg < long_term_avg * 0.5:
            if rms_slope > 0:
                return MusicStructure.INTRO, 0.0
            else:
                return MusicStructure.OUTRO, 0.0

        return self._current_structure, drop_prob

    def _calculate_slope(self, values: list[float]) -> float:
        """Calculate linear slope of values."""
        if len(values) < 10:
            return 0.0
        x = np.arange(len(values))
        coeffs = np.polyfit(x, values, 1)
        return float(coeffs[0])

    def _calculate_confidence(self) -> float:
        """Calculate confidence in current structure classification."""
        if len(self._rms_history) < 100:
            return 0.3  # Low confidence with little history

        # Confidence based on feature stability
        rms_std = np.std(list(self._rms_history)[-50:])
        rms_mean = np.mean(list(self._rms_history)[-50:])

        if rms_mean > 0:
            cv = rms_std / rms_mean  # Coefficient of variation
            # Lower CV = more stable = higher confidence
            confidence = max(0.0, min(1.0, 1.0 - cv))
        else:
            confidence = 0.5

        return cast(float, confidence)
