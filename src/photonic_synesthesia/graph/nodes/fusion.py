"""
Fusion Node: Multi-modal sensor fusion.

Combines data from audio analysis, MIDI, and computer vision
to produce a coherent understanding of the current musical moment.
"""

from __future__ import annotations

import time

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
            state["drop_probability"] = max(state["drop_probability"], lookahead_bass * 0.5)

        # =================================================================
        # MIDI Override Detection
        # =================================================================
        midi_state = state["midi_state"]

        # Fader-based intensity scaling
        # If DJ is fading out a channel, reduce intensity
        active_faders = [f for f in midi_state["channel_faders"] if f > 0.1]
        if active_faders:
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

        # =================================================================
        # Dual-stream output (rule stream + ML stream)
        # =================================================================
        state["rule_stream"]["low_band"] = float(state["audio_features"]["low_energy"])
        state["rule_stream"]["mid_band"] = float(state["audio_features"]["mid_energy"])
        state["rule_stream"]["high_band"] = float(state["audio_features"]["high_energy"])
        state["rule_stream"]["transient"] = float(state["audio_features"]["spectral_flux"])
        state["rule_stream"]["beat_pulse"] = 1.0 if state["beat_info"]["beat_phase"] < 0.12 else 0.0

        ml_scene = self._predict_scene(state)
        state["ml_stream"]["predicted_scene"] = ml_scene
        state["ml_stream"]["confidence"] = self._predict_confidence(state)
        state["ml_stream"]["horizon_ms"] = 250
        state["sensor_status"]["ml"] = True

        # Record processing time
        state["processing_times"]["fusion"] = time.time() - start_time

        return state

    def _fuse_bpm(
        self,
        audio_bpm: float,
        cv_bpm: float | None,
        audio_confidence: float,
    ) -> float:
        """
        Fuse BPM estimates from audio and CV.

        Uses weighted average with smoothing.
        """
        if cv_bpm is not None and 60 < cv_bpm < 200:
            # Both sources available - weighted average
            if audio_confidence > 0.5:
                fused = audio_bpm * self.audio_bpm_weight + cv_bpm * self.cv_bpm_weight
            else:
                # Low audio confidence - trust CV more
                fused = cv_bpm * 0.8 + audio_bpm * 0.2
        else:
            # Only audio available
            fused = audio_bpm

        # Smooth to prevent jitter
        self._fused_bpm = self._fused_bpm * self.bpm_smoothing + fused * (1 - self.bpm_smoothing)

        return self._fused_bpm

    def _determine_bpm_source(
        self,
        audio_confidence: float,
        cv_bpm: float | None,
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

    def _predict_scene(self, state: PhotonicState) -> str:
        """
        Lightweight ML-stream proxy for scene prediction.

        This is intentionally heuristic for now; it occupies the contract slot
        where a learned scene classifier can be plugged in later.
        """
        if state["cv_state"]["lookahead_bass"] > 0.8 and state["drop_probability"] > 0.6:
            return "drop_intense"

        structure = state["current_structure"].value
        scene_map = {
            "intro": "intro_ambient",
            "verse": "verse_rhythmic",
            "buildup": "buildup_tension",
            "drop": "drop_intense",
            "breakdown": "breakdown_ambient",
            "outro": "outro_fade",
            "unknown": "idle",
        }
        return scene_map.get(structure, "idle")

    def _predict_confidence(self, state: PhotonicState) -> float:
        beat_confidence = float(state["beat_info"]["confidence"])
        has_cv = 1.0 if state["cv_state"]["detected_bpm"] is not None else 0.0
        score = (beat_confidence * 0.7) + (has_cv * 0.3)
        return min(1.0, max(0.0, score))
