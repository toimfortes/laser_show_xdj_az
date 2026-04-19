"""
Feature Extraction Node: Spectral and temporal audio feature extraction.

Uses librosa to compute RMS energy, spectral centroid, spectral flux,
band energies, and MFCCs from the audio buffer.
"""

from __future__ import annotations

import time
import warnings
from typing import Any

import numpy as np
from numpy.typing import NDArray

from photonic_synesthesia.core.logging import get_logger
from photonic_synesthesia.core.state import AudioFeatures, PhotonicState

logger = get_logger(__name__)

# Import librosa conditionally
_librosa: Any = None
try:
    import librosa as _librosa_import
except ImportError:
    LIBROSA_AVAILABLE = False
else:
    _librosa = _librosa_import
    LIBROSA_AVAILABLE = True

librosa: Any = _librosa


class FeatureExtractNode:
    """
    Extracts spectral and temporal features from audio buffer.

    Features extracted:
    - RMS energy (overall loudness)
    - Spectral centroid (brightness)
    - Spectral flux (rate of change)
    - Spectral rolloff (frequency below which X% of energy exists)
    - Band energies (low/mid/high frequency bands)
    - Harmonic/percussive balance
    - Tonal stability and harmonic change
    - Pitch salience / approximate pitch height
    - Timbral harshness
    - MFCCs (timbral fingerprint)
    """

    def __init__(
        self,
        n_fft: int = 2048,
        hop_length: int = 512,
        n_mfcc: int = 13,
        n_mels: int = 128,
        streaming_dsp: bool = False,
    ):
        self.n_fft = n_fft
        self.hop_length = hop_length
        self.n_mfcc = n_mfcc
        self.n_mels = n_mels
        self.streaming_dsp = streaming_dsp

        # Frequency band boundaries (Hz)
        self.low_band = (20, 200)  # Sub-bass and bass
        self.mid_band = (200, 2000)  # Vocals, instruments
        self.high_band = (2000, 20000)  # Cymbals, hi-hats, air

        # Previous spectrum for flux calculation
        self._prev_spectrum: NDArray | None = None
        self._warned_missing_librosa = False

    def __call__(self, state: PhotonicState) -> PhotonicState:
        """Extract audio features and update state."""
        start_time = time.time()

        if not LIBROSA_AVAILABLE:
            if not self._warned_missing_librosa:
                logger.warning("librosa not available, using dummy features")
                self._warned_missing_librosa = True
            return self._dummy_features(state)

        audio_buffer = state.get("audio_buffer", [])
        if len(audio_buffer) < self.n_fft:
            # Not enough samples yet
            return state

        try:
            # Convert to numpy array
            y = np.array(audio_buffer, dtype=np.float32)
            sr = state.get("sample_rate", 48000)

            # Compute features
            features = self._extract_features(y, sr)

            # Update state
            state["audio_features"] = features

        except Exception as e:
            logger.error("Feature extraction failed", error=str(e))
            state["safety_state"]["error_state"] = f"feature_extract: {e}"

        # Record processing time
        state["processing_times"]["feature_extract"] = time.time() - start_time

        return state

    def _extract_features(self, y: NDArray, sr: int) -> AudioFeatures:
        """Extract all audio features from signal."""
        effective_n_fft = max(32, min(self.n_fft, int(y.size)))
        effective_hop_length = max(1, min(self.hop_length, effective_n_fft))

        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"n_fft=.* is too large for input signal of length=.*",
                category=UserWarning,
            )
            spectrum = np.abs(
                librosa.stft(y, n_fft=effective_n_fft, hop_length=effective_hop_length)
            )

            # RMS energy
            rms = librosa.feature.rms(
                y=y,
                frame_length=effective_n_fft,
                hop_length=effective_hop_length,
            )
            rms_mean = float(np.mean(rms))

            # Spectral centroid (brightness)
            centroid = librosa.feature.spectral_centroid(
                y=y,
                sr=sr,
                n_fft=effective_n_fft,
                hop_length=effective_hop_length,
            )
            centroid_mean = float(np.mean(centroid))

            # Spectral rolloff
            rolloff = librosa.feature.spectral_rolloff(
                y=y,
                sr=sr,
                n_fft=effective_n_fft,
                hop_length=effective_hop_length,
            )
            rolloff_mean = float(np.mean(rolloff))

            # Spectral flux (onset strength as proxy)
            onset_env = librosa.onset.onset_strength(
                y=y,
                sr=sr,
                n_fft=effective_n_fft,
                hop_length=effective_hop_length,
            )
            flux_mean = float(np.mean(onset_env))

            harmonic_spectrum, percussive_spectrum = librosa.decompose.hpss(spectrum, margin=2.0)
            harmonic_energy = float(np.mean(harmonic_spectrum))
            percussive_energy = float(np.mean(percussive_spectrum))
            total_hp_energy = max(harmonic_energy + percussive_energy, 1e-6)
            harmonic_ratio = harmonic_energy / total_hp_energy
            percussive_ratio = percussive_energy / total_hp_energy

            # Mel spectrogram for band energies
            mel = librosa.feature.melspectrogram(
                y=y,
                sr=sr,
                n_fft=effective_n_fft,
                hop_length=effective_hop_length,
                n_mels=self.n_mels,
            )

            # Convert mel bins to approximate frequency bands
            # Mel scale is non-linear, so we use approximate bin ranges
            low_bins = int(self.n_mels * 0.1)  # ~0-200 Hz
            mid_bins = int(self.n_mels * 0.5)  # ~200-2000 Hz
            # Remaining bins are high

            low_energy = float(np.mean(mel[:low_bins, :]))
            mid_energy = float(np.mean(mel[low_bins:mid_bins, :]))
            high_energy = float(np.mean(mel[mid_bins:, :]))

            chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=effective_hop_length)
            if chroma.shape[1] > 1:
                chroma_delta = np.abs(np.diff(chroma, axis=1))
                harmonic_change = float(np.mean(chroma_delta))
                tonal_stability = float(np.clip(1.0 - (harmonic_change * 1.6), 0.0, 1.0))
            else:
                harmonic_change = 0.0
                tonal_stability = 0.0

            tonnetz = librosa.feature.tonnetz(y=librosa.effects.harmonic(y), sr=sr)
            if tonnetz.shape[1] > 1:
                tonnetz_delta = np.linalg.norm(np.diff(tonnetz, axis=1), axis=0)
                harmonic_change = float(
                    np.clip(
                        (harmonic_change * 0.6) + (float(np.mean(tonnetz_delta)) * 0.4),
                        0.0,
                        1.0,
                    )
                )
                tonal_stability = float(np.clip(1.0 - harmonic_change, 0.0, 1.0))
            harmonic_tension = float(
                np.clip(
                    (harmonic_change * 0.58)
                    + ((1.0 - tonal_stability) * 0.27)
                    + (np.clip(float(np.std(chroma)) * 0.65, 0.0, 1.0) * 0.15),
                    0.0,
                    1.0,
                )
            )

            dominant_pitch_track = np.array([], dtype=np.float32)
            pyin_pitch_track = np.array([], dtype=np.float32)
            try:
                pyin_f0, pyin_voiced, _ = librosa.pyin(
                    y,
                    fmin=librosa.note_to_hz("C2"),
                    fmax=librosa.note_to_hz("C7"),
                    sr=sr,
                    frame_length=effective_n_fft,
                    hop_length=effective_hop_length,
                )
                if pyin_f0 is not None and pyin_voiced is not None:
                    pyin_pitch_track = np.asarray(
                        pyin_f0[np.asarray(pyin_voiced, dtype=bool)],
                        dtype=np.float32,
                    )
            except Exception:
                pyin_pitch_track = np.array([], dtype=np.float32)

            pitches, magnitudes = librosa.piptrack(
                S=harmonic_spectrum,
                sr=sr,
                n_fft=effective_n_fft,
                hop_length=effective_hop_length,
                fmin=60.0,
                fmax=2000.0,
            )
            frame_max_magnitudes = np.max(magnitudes, axis=0) if magnitudes.size else np.array([0.0])
            overall_max_magnitude = max(float(np.max(magnitudes)) if magnitudes.size else 0.0, 1e-6)
            pitch_salience = float(
                np.clip(np.mean(frame_max_magnitudes) / overall_max_magnitude, 0.0, 1.0)
            )
            if magnitudes.size and np.any(frame_max_magnitudes > 0):
                dominant_indices = np.argmax(magnitudes, axis=0)
                dominant_pitch_track = pitches[dominant_indices, np.arange(pitches.shape[1])]
                dominant_pitch_track = dominant_pitch_track[dominant_pitch_track > 0]
            valid_pitches = pyin_pitch_track if pyin_pitch_track.size > 0 else dominant_pitch_track
            if valid_pitches.size > 0:
                median_pitch = float(np.median(valid_pitches))
                pitch_height = float(np.clip((median_pitch - 80.0) / (1200.0 - 80.0), 0.0, 1.0))
                if valid_pitches.size > 1:
                    log_pitches = np.log2(np.maximum(valid_pitches, 1e-6))
                    melodic_contour = float(
                        np.clip((np.mean(np.diff(log_pitches)) * 18.0) + 0.5, 0.0, 1.0)
                    )
                    melodic_stability = float(
                        np.clip(1.0 - (np.std(log_pitches) * 3.2), 0.0, 1.0)
                    )
                else:
                    melodic_contour = 0.5
                    melodic_stability = 1.0
            else:
                pitch_height = 0.0
                melodic_contour = 0.5
                melodic_stability = 0.0

            if onset_env.size > 0:
                onset_threshold = float(np.mean(onset_env) + (0.35 * np.std(onset_env)))
                onset_density = float(np.clip(np.mean(onset_env > onset_threshold), 0.0, 1.0))
            else:
                onset_density = 0.0

            flatness = librosa.feature.spectral_flatness(S=np.maximum(spectrum, 1e-10))
            flatness_mean = float(np.mean(flatness))
            centroid_norm = float(np.clip(centroid_mean / max(sr / 2.0, 1.0), 0.0, 1.0))
            high_band_ratio = high_energy / max(low_energy + mid_energy + high_energy, 1e-6)
            timbral_harshness = float(
                np.clip(
                    (centroid_norm * 0.42) + (flatness_mean * 0.33) + (high_band_ratio * 0.25),
                    0.0,
                    1.0,
                )
            )

            # MFCCs (timbral fingerprint)
            mfcc = librosa.feature.mfcc(
                y=y,
                sr=sr,
                n_mfcc=self.n_mfcc,
                n_fft=effective_n_fft,
                hop_length=effective_hop_length,
            )
            mfcc_vector = mfcc.mean(axis=1).tolist()

        return AudioFeatures(
            rms_energy=rms_mean,
            spectral_centroid=centroid_mean,
            spectral_flux=flux_mean,
            spectral_rolloff=rolloff_mean,
            low_energy=low_energy,
            mid_energy=mid_energy,
            high_energy=high_energy,
            harmonic_ratio=harmonic_ratio,
            percussive_ratio=percussive_ratio,
            tonal_stability=tonal_stability,
            harmonic_change=harmonic_change,
            harmonic_tension=harmonic_tension,
            pitch_salience=pitch_salience,
            pitch_height=pitch_height,
            melodic_contour=melodic_contour,
            melodic_stability=melodic_stability,
            onset_density=onset_density,
            timbral_harshness=timbral_harshness,
            mfcc_vector=mfcc_vector,
        )

    def _dummy_features(self, state: PhotonicState) -> PhotonicState:
        """Return dummy features when librosa is not available."""
        state["audio_features"] = AudioFeatures(
            rms_energy=0.0,
            spectral_centroid=0.0,
            spectral_flux=0.0,
            spectral_rolloff=0.0,
            low_energy=0.0,
            mid_energy=0.0,
            high_energy=0.0,
            harmonic_ratio=0.0,
            percussive_ratio=0.0,
            tonal_stability=0.0,
            harmonic_change=0.0,
            harmonic_tension=0.0,
            pitch_salience=0.0,
            pitch_height=0.0,
            melodic_contour=0.0,
            melodic_stability=0.0,
            onset_density=0.0,
            timbral_harshness=0.0,
            mfcc_vector=[0.0] * self.n_mfcc,
        )
        return state
