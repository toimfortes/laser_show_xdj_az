"""
Fusion Node: Multi-modal sensor fusion.

Combines data from audio analysis, MIDI, and computer vision
to produce a coherent understanding of the current musical moment.
"""

from __future__ import annotations

import time
from typing import Optional
import structlog

from photonic_synesthesia.core.state import PhotonicState

logger = structlog.get_logger()


class FusionNode:
    """
    Fuses data from multiple sensor modalities.

    Key responsibilities:
    - Combine audio and CV BPM estimates
    - Weight features based on sensor confidence
    - Resolve conflicts between sources
    - Apply MIDI overrides where appropriate
    """

    def __init__(
        self,
        audio_bpm_weight: float = 0.7,
        cv_bpm_weight: float = 0.3,
        bpm_smoothing: float = 0.9,
    ):
        self.audio_bpm_weight = audio_bpm_weight
        self.cv_bpm_weight = cv_bpm_weight
        self.bpm_smoothing = bpm_smoothing

        self._fused_bpm: float = 128.0

    def __call__(self, state: PhotonicState) -> PhotonicState:
        """Fuse sensor data and update state."""
        start_time = time.time()

        # =================================================================
        # BPM Fusion
        # =================================================================
        audio_bpm = state["beat_info"]["bpm"]
        cv_bpm = state["cv_state"]["detected_bpm"]
        audio_confidence = state["beat_info"]["confidence"]

        new_bpm = self._fuse_bpm(audio_bpm, cv_bpm, audio_confidence)
        state["fused_bpm"] = new_bpm
        state["bpm_source"] = self._determine_bpm_source(audio_confidence, cv_bpm)

        # =================================================================
        # Energy/Intensity Fusion
        # =================================================================
        # Combine audio RMS with CV lookahead for anticipatory response
        audio_energy = state["audio_features"]["rms_energy"]
        lookahead_bass = state["cv_state"]["lookahead_bass"]

        # If CV shows bass incoming but audio doesn't have it yet, anticipate
        if lookahead_bass > 0.7 and audio_energy < 0.3:
            state["drop_probability"] = max(
                state["drop_probability"],
                lookahead_bass * 0.5
            )

        # =================================================================
        # MIDI Override Detection
        # =================================================================
        midi_state = state["midi_state"]

        # Fader-based intensity scaling
        # If DJ is fading out a channel, reduce intensity
        active_faders = [f for f in midi_state["channel_faders"] if f > 0.1]
        if active_faders:
            fader_intensity = max(active_faders)
            # This can be used by scene selection for dimming
            state["midi_state"]["channel_faders"] = midi_state["channel_faders"]

        # Pad triggers indicate manual override intent
        if midi_state["pad_triggers"]:
            logger.debug("Pad triggers detected", pads=midi_state["pad_triggers"])
            # These will be handled by scene_select node

        # =================================================================
        # Filter State to Lighting
        # =================================================================
        # When DJ uses high-pass filter, we should thin out the lighting
        # Average filter position (0.5 = neutral)
        avg_filter = sum(midi_state["filter_positions"]) / 4
        if avg_filter > 0.7:  # Heavy high-pass
            # This could dim bass-related fixtures
            pass
        elif avg_filter < 0.3:  # Heavy low-pass
            # This could dim high-frequency effects
            pass

        # Record processing time
        state["processing_times"]["fusion"] = time.time() - start_time

        return state

    def _fuse_bpm(
        self,
        audio_bpm: float,
        cv_bpm: Optional[float],
        audio_confidence: float,
    ) -> float:
        """
        Fuse BPM estimates from audio and CV.

        Uses weighted average with smoothing.
        """
        if cv_bpm is not None and 60 < cv_bpm < 200:
            # Both sources available - weighted average
            if audio_confidence > 0.5:
                fused = (
                    audio_bpm * self.audio_bpm_weight +
                    cv_bpm * self.cv_bpm_weight
                )
            else:
                # Low audio confidence - trust CV more
                fused = cv_bpm * 0.8 + audio_bpm * 0.2
        else:
            # Only audio available
            fused = audio_bpm

        # Smooth to prevent jitter
        self._fused_bpm = (
            self._fused_bpm * self.bpm_smoothing +
            fused * (1 - self.bpm_smoothing)
        )

        return self._fused_bpm

    def _determine_bpm_source(
        self,
        audio_confidence: float,
        cv_bpm: Optional[float],
    ) -> str:
        """Determine which source is primary for BPM."""
        if cv_bpm is not None and audio_confidence < 0.5:
            return "cv"
        elif audio_confidence > 0.7:
            return "audio"
        elif cv_bpm is not None:
            return "fused"
        else:
            return "audio"
