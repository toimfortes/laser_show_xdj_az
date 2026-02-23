"""
Feature Extraction Node: Spectral and temporal audio feature extraction.

Uses librosa to compute RMS energy, spectral centroid, spectral flux,
band energies, and MFCCs from the audio buffer.
"""

from __future__ import annotations

import time

import numpy as np
import structlog
from numpy.typing import NDArray

from photonic_synesthesia.core.state import AudioFeatures, PhotonicState

logger = structlog.get_logger()

# Import librosa conditionally
try:
    import librosa

    LIBROSA_AVAILABLE = True
except ImportError:
    LIBROSA_AVAILABLE = False
    librosa = None


class FeatureExtractNode:
    """
    Extracts spectral and temporal features from audio buffer.

    Features extracted:
    - RMS energy (overall loudness)
    - Spectral centroid (brightness)
    - Spectral flux (rate of change)
    - Spectral rolloff (frequency below which X% of energy exists)
    - Band energies (low/mid/high frequency bands)
    - MFCCs (timbral fingerprint)
    """

    def __init__(
        self,
        n_fft: int = 2048,
        hop_length: int = 512,
        n_mfcc: int = 13,
        n_mels: int = 128,
    ):
        self.n_fft = n_fft
        self.hop_length = hop_length
        self.n_mfcc = n_mfcc
        self.n_mels = n_mels

        # Frequency band boundaries (Hz)
        self.low_band = (20, 200)  # Sub-bass and bass
        self.mid_band = (200, 2000)  # Vocals, instruments
        self.high_band = (2000, 20000)  # Cymbals, hi-hats, air

        # Previous spectrum for flux calculation
        self._prev_spectrum: NDArray | None = None

    def __call__(self, state: PhotonicState) -> PhotonicState:
        """Extract audio features and update state."""
        start_time = time.time()

        if not LIBROSA_AVAILABLE:
            logger.warning("librosa not available, using dummy features")
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
        # RMS energy
        rms = librosa.feature.rms(y=y, frame_length=self.n_fft, hop_length=self.hop_length)
        rms_mean = float(np.mean(rms))

        # Spectral centroid (brightness)
        centroid = librosa.feature.spectral_centroid(
            y=y, sr=sr, n_fft=self.n_fft, hop_length=self.hop_length
        )
        centroid_mean = float(np.mean(centroid))

        # Spectral rolloff
        rolloff = librosa.feature.spectral_rolloff(
            y=y, sr=sr, n_fft=self.n_fft, hop_length=self.hop_length
        )
        rolloff_mean = float(np.mean(rolloff))

        # Spectral flux (onset strength as proxy)
        onset_env = librosa.onset.onset_strength(
            y=y, sr=sr, n_fft=self.n_fft, hop_length=self.hop_length
        )
        flux_mean = float(np.mean(onset_env))

        # Mel spectrogram for band energies
        mel = librosa.feature.melspectrogram(
            y=y, sr=sr, n_fft=self.n_fft, hop_length=self.hop_length, n_mels=self.n_mels
        )

        # Convert mel bins to approximate frequency bands
        # Mel scale is non-linear, so we use approximate bin ranges
        low_bins = int(self.n_mels * 0.1)  # ~0-200 Hz
        mid_bins = int(self.n_mels * 0.5)  # ~200-2000 Hz
        # Remaining bins are high

        low_energy = float(np.mean(mel[:low_bins, :]))
        mid_energy = float(np.mean(mel[low_bins:mid_bins, :]))
        high_energy = float(np.mean(mel[mid_bins:, :]))

        # MFCCs (timbral fingerprint)
        mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=self.n_mfcc)
        mfcc_vector = mfcc.mean(axis=1).tolist()

        return AudioFeatures(
            rms_energy=rms_mean,
            spectral_centroid=centroid_mean,
            spectral_flux=flux_mean,
            spectral_rolloff=rolloff_mean,
            low_energy=low_energy,
            mid_energy=mid_energy,
            high_energy=high_energy,
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
            mfcc_vector=[0.0] * self.n_mfcc,
        )
        return state
