"""
Feature Extraction Node: Spectral and temporal audio feature extraction.

Uses librosa to compute RMS energy, spectral centroid, spectral flux,
band energies, and MFCCs from the audio buffer.

## Hot-path / cold-path split (Review A — run-file frame-budget)

The cycle-1 destructive review (Review A: Codex run-file perf) flagged
this node as the dominant cost in the 50 Hz graph tick: median
**~650 ms / tick** versus a **20 ms budget** (32× over). Profile showed
the cost concentrated in:

  - `librosa.pyin`            — 443 ms / call (68% of total)
  - `librosa.decompose.hpss`  —  74 ms / call (11%)
  - `librosa.feature.chroma_cqt` + `librosa.constantq.cqt` — 90 ms (14%)

Once feature_extract overran the budget, downstream `IldaTransportNode`
and `DmxOutputNode` stalled, the SafetyMonitor watchdog fired, and the
runtime emergency-blackouted in a loop while the playhead barely moved.

The fix is a **two-tier extraction**:

  1. **LIGHT path** runs every tick on the main thread (~14 ms median):
     STFT, RMS, spectral centroid / rolloff, onset strength, mel band
     energies, MFCCs, spectral flatness, timbral harshness.

  2. **HEAVY path** runs in a single-thread background analyzer
     (`_HarmonicAnalyzer`) at whatever cadence the worker can sustain
     (~1.5 Hz at 2 s buffers): pyin (pitch tracking), hpss (harmonic /
     percussive split), chroma_cqt + tonnetz (harmonic_change /
     tonal_stability / harmonic_tension), piptrack (pitch_salience).
     Submissions are **latest-wins** — if the worker is still busy when
     a new buffer arrives, the new buffer is dropped (we don't pile up
     a backlog of stale work).

The main tick reads the latest harmonic snapshot from the analyzer; if
none is ready yet (first ~1 s of the show), it uses neutral defaults.
This converts a 32× overrun into a 14 ms tick that hits the 50 Hz
budget with headroom, while pitch / harmonic features update at
human-perceptible rates (~1–2 Hz) which is more than enough to drive
director-palette / harmonic_tension visuals.

`_extract_features(y, sr)` retains its full synchronous semantics so
existing tests (`test_production_hardening`, the analyze CLI) get
identical full-spectrum results — only `__call__` (the per-tick path)
uses the async route.
"""

from __future__ import annotations

import concurrent.futures
import multiprocessing
import threading
import time
import warnings
from concurrent.futures.process import BrokenProcessPool
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


# Default harmonic snapshot used by the LIGHT path on ticks that arrive
# before the background analyzer has produced its first result. Tonal
# stability defaults to 0.5 (neutral) and pitch_height to 0.0 (silence).
_NEUTRAL_HARMONIC: dict[str, float] = {
    "harmonic_ratio": 0.5,
    "percussive_ratio": 0.5,
    "harmonic_change": 0.0,
    "tonal_stability": 0.5,
    "harmonic_tension": 0.0,
    "pitch_salience": 0.0,
    "pitch_height": 0.0,
    "melodic_contour": 0.5,
    "melodic_stability": 0.0,
}


def _compute_heavy_features(y: NDArray, sr: int, n_fft: int, hop: int) -> dict[str, float]:
    """Module-level heavy-DSP function — picklable for ProcessPool dispatch.

    Cycle-1 Review A v2: must be module-level (not a method) so the
    ProcessPoolExecutor can pickle it for transport to the worker
    process. Methods on classes that hold thread locks aren't
    picklable; module-level functions are.
    """
    # Re-import librosa inside the worker process — the module-level
    # `librosa` here is from the parent's import; the spawned worker
    # process imports its own when this function is first called.
    import librosa as _wlib
    import numpy as _wnp

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"n_fft=.* is too large for input signal of length=.*",
            category=UserWarning,
        )

        spectrum = _wnp.abs(_wlib.stft(y, n_fft=n_fft, hop_length=hop))
        harmonic_spec, percussive_spec = _wlib.decompose.hpss(spectrum, margin=2.0)
        harmonic_energy = float(_wnp.mean(harmonic_spec))
        percussive_energy = float(_wnp.mean(percussive_spec))
        total_hp = max(harmonic_energy + percussive_energy, 1e-6)
        harmonic_ratio = harmonic_energy / total_hp
        percussive_ratio = percussive_energy / total_hp

        # chroma → harmonic_change / tonal_stability seed
        harmonic_change = 0.0
        tonal_stability = 0.0
        chroma_std = 0.0
        chroma = _wlib.feature.chroma_cqt(y=y, sr=sr, hop_length=hop)
        if chroma.shape[1] > 1:
            chroma_delta = _wnp.abs(_wnp.diff(chroma, axis=1))
            harmonic_change = float(_wnp.mean(chroma_delta))
            tonal_stability = float(_wnp.clip(1.0 - (harmonic_change * 1.6), 0.0, 1.0))
            chroma_std = float(_wnp.std(chroma))

        # tonnetz refines harmonic_change / tonal_stability
        harmonic_audio = _wnp.asarray(_wlib.effects.harmonic(y), dtype=_wnp.float32)
        if _wnp.isfinite(harmonic_audio).all():
            tonnetz = _wlib.feature.tonnetz(y=harmonic_audio, sr=sr)
            if tonnetz.shape[1] > 1:
                tonnetz_delta = _wnp.linalg.norm(_wnp.diff(tonnetz, axis=1), axis=0)
                harmonic_change = float(
                    _wnp.clip(
                        (harmonic_change * 0.6) + (float(_wnp.mean(tonnetz_delta)) * 0.4),
                        0.0,
                        1.0,
                    )
                )
                tonal_stability = float(_wnp.clip(1.0 - harmonic_change, 0.0, 1.0))

        harmonic_tension = float(
            _wnp.clip(
                (harmonic_change * 0.58)
                + ((1.0 - tonal_stability) * 0.27)
                + (_wnp.clip(chroma_std * 0.65, 0.0, 1.0) * 0.15),
                0.0,
                1.0,
            )
        )

        # pitch tracking: pyin + piptrack fallback
        pyin_track = _wnp.array([], dtype=_wnp.float32)
        try:
            pyin_f0, pyin_voiced, _ = _wlib.pyin(
                y,
                fmin=_wlib.note_to_hz("C2"),
                fmax=_wlib.note_to_hz("C7"),
                sr=sr,
                frame_length=n_fft,
                hop_length=hop,
            )
            if pyin_f0 is not None and pyin_voiced is not None:
                pyin_track = _wnp.asarray(
                    pyin_f0[_wnp.asarray(pyin_voiced, dtype=bool)],
                    dtype=_wnp.float32,
                )
        except Exception:
            pyin_track = _wnp.array([], dtype=_wnp.float32)

        pitches, magnitudes = _wlib.piptrack(
            S=harmonic_spec, sr=sr, n_fft=n_fft, hop_length=hop, fmin=60.0, fmax=2000.0,
        )
        frame_max = _wnp.max(magnitudes, axis=0) if magnitudes.size else _wnp.array([0.0])
        overall_max = max(float(_wnp.max(magnitudes)) if magnitudes.size else 0.0, 1e-6)
        pitch_salience = float(_wnp.clip(_wnp.mean(frame_max) / overall_max, 0.0, 1.0))

        dom_track = _wnp.array([], dtype=_wnp.float32)
        if magnitudes.size and _wnp.any(frame_max > 0):
            dom_idx = _wnp.argmax(magnitudes, axis=0)
            dom_track = pitches[dom_idx, _wnp.arange(pitches.shape[1])]
            dom_track = dom_track[dom_track > 0]

        valid_pitches = pyin_track if pyin_track.size > 0 else dom_track
        if valid_pitches.size > 0:
            median_pitch = float(_wnp.median(valid_pitches))
            pitch_height = float(_wnp.clip((median_pitch - 80.0) / (1200.0 - 80.0), 0.0, 1.0))
            if valid_pitches.size > 1:
                log_pitches = _wnp.log2(_wnp.maximum(valid_pitches, 1e-6))
                melodic_contour = float(_wnp.clip((_wnp.mean(_wnp.diff(log_pitches)) * 18.0) + 0.5, 0.0, 1.0))
                melodic_stability = float(_wnp.clip(1.0 - (_wnp.std(log_pitches) * 3.2), 0.0, 1.0))
            else:
                melodic_contour = 0.5
                melodic_stability = 1.0
        else:
            pitch_height = 0.0
            melodic_contour = 0.5
            melodic_stability = 0.0

    return {
        "harmonic_ratio": harmonic_ratio,
        "percussive_ratio": percussive_ratio,
        "harmonic_change": harmonic_change,
        "tonal_stability": tonal_stability,
        "harmonic_tension": harmonic_tension,
        "pitch_salience": pitch_salience,
        "pitch_height": pitch_height,
        "melodic_contour": melodic_contour,
        "melodic_stability": melodic_stability,
    }


class _HarmonicAnalyzer:
    """Background worker for the cycle-1 Review A heavy DSP split.

    Cycle-1 Review A v2: uses a ProcessPoolExecutor (not thread pool)
    because the heavy DSP includes `librosa.pyin` which runs a Python
    Viterbi decoder that holds the GIL. With a thread pool, the main
    tick stalled for ~450 ms p95 waiting for the GIL even though the
    work was "background." A separate process is GIL-free.

    Submissions are `latest-wins`: if the worker is busy, the incoming
    buffer is dropped — never queued.

    Thread-safety: `_latest`, `_inflight` and `_pending_future` are
    guarded by `_lock`.
    """

    def __init__(self, *, n_fft: int, hop_length: int) -> None:
        self._n_fft = n_fft
        self._hop_length = hop_length
        self._lock = threading.Lock()
        self._latest: dict[str, float] | None = None
        self._inflight = False
        self._stopped = False
        # ProcessPool — single worker process (we want at-most-one
        # heavy DSP job in flight). Created lazily on first submit so
        # node construction stays cheap.
        self._executor: concurrent.futures.ProcessPoolExecutor | None = None

    def _ensure_executor(self) -> concurrent.futures.ProcessPoolExecutor | None:
        if self._executor is None and not self._stopped:
            try:
                # Use `spawn` — `fork` emits a DeprecationWarning in
                # multi-threaded processes (librosa imports pull in
                # many threads) and can deadlock under the hood.
                # `spawn` is ~200ms slower on first submit but rock-solid.
                ctx = multiprocessing.get_context("spawn")
                self._executor = concurrent.futures.ProcessPoolExecutor(
                    max_workers=1, mp_context=ctx,
                )
            except Exception as exc:
                logger.warning("harmonic_analyzer_executor_init_failed", error=str(exc))
                self._stopped = True
                return None
        return self._executor

    def submit(self, y: NDArray, sr: int) -> None:
        """Submit a buffer for background analysis. No-op if a job is
        already running (latest-wins) or the analyzer is shut down."""
        with self._lock:
            if self._inflight or self._stopped:
                return
            executor = self._ensure_executor()
            if executor is None:
                return
            self._inflight = True
        # Pickle a copy outside the lock so the producer can mutate
        # its rolling buffer freely.
        try:
            future = executor.submit(
                _compute_heavy_features,
                np.asarray(y, dtype=np.float32).copy(),
                int(sr),
                self._n_fft,
                self._hop_length,
            )
        except (RuntimeError, BrokenProcessPool) as exc:
            logger.warning("harmonic_analyzer_submit_failed", error=str(exc))
            with self._lock:
                self._inflight = False
            return
        future.add_done_callback(self._on_done)

    def _on_done(self, future: concurrent.futures.Future) -> None:
        result: dict[str, float] | None
        try:
            result = future.result()
        except Exception as exc:
            logger.warning("harmonic_analyzer_failed", error=str(exc))
            result = None
        with self._lock:
            if result is not None:
                self._latest = result
            self._inflight = False

    def _compute(self, y: NDArray, sr: int) -> dict[str, float]:
        """Synchronous fallback — delegates to the module-level
        function so the implementation is shared with the bg worker."""
        return _compute_heavy_features(
            np.asarray(y, dtype=np.float32),
            int(sr),
            self._n_fft,
            self._hop_length,
        )

    def latest(self) -> dict[str, float]:
        """Return a copy of the most recent harmonic snapshot, or
        neutral defaults if the analyzer hasn't produced one yet."""
        with self._lock:
            if self._latest is None:
                return dict(_NEUTRAL_HARMONIC)
            return dict(self._latest)

    def close(self) -> None:
        with self._lock:
            self._stopped = True
        # `wait=False` so a slow in-flight pyin doesn't block process
        # shutdown. The thread is daemonized via the executor anyway.
        try:
            self._executor.shutdown(wait=False)
        except Exception:
            pass


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

        # Cycle-1 Review A: per-instance background analyzer for the
        # heavy DSP path. Created lazily on first __call__ since some
        # callers (the analyze CLI subcommand) prefer the synchronous
        # `_extract_features` route and shouldn't pay the thread setup.
        self._harmonic_analyzer: _HarmonicAnalyzer | None = None

    def _get_or_create_analyzer(self) -> _HarmonicAnalyzer:
        if self._harmonic_analyzer is None:
            self._harmonic_analyzer = _HarmonicAnalyzer(
                n_fft=self.n_fft, hop_length=self.hop_length,
            )
        return self._harmonic_analyzer

    def close(self) -> None:
        """Shut down the background analyzer (if any)."""
        if self._harmonic_analyzer is not None:
            self._harmonic_analyzer.close()
            self._harmonic_analyzer = None

    def __call__(self, state: PhotonicState) -> PhotonicState:
        """Extract audio features and update state.

        Cycle-1 Review A: this is the HOT PATH (50 Hz). It runs the
        LIGHT extraction synchronously and consumes the latest
        background-computed harmonic snapshot. Heavy DSP (pyin, hpss,
        chroma, tonnetz) is offloaded to `_HarmonicAnalyzer` so the
        graph tick stays under its 20 ms / 50 Hz budget.
        """
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
            y = np.array(audio_buffer, dtype=np.float32)
            sr = state.get("sample_rate", 48000)

            # Cycle-1 Review A: submit current buffer to the background
            # analyzer (latest-wins, non-blocking) and read its latest
            # snapshot. Light path computes everything else inline.
            analyzer = self._get_or_create_analyzer()
            analyzer.submit(y, sr)
            harmonic = analyzer.latest()

            features = self._extract_features(y, sr, harmonic_overrides=harmonic)

            state["audio_features"] = features

        except Exception as e:
            logger.error("Feature extraction failed", error=str(e))
            state["safety_state"]["error_state"] = f"feature_extract: {e}"

        state["processing_times"]["feature_extract"] = time.time() - start_time
        return state

    def _extract_features(
        self,
        y: NDArray,
        sr: int,
        *,
        harmonic_overrides: dict[str, float] | None = None,
    ) -> AudioFeatures:
        """Extract all audio features from signal.

        If `harmonic_overrides` is supplied (the per-tick HOT PATH from
        `__call__`), the heavy DSP block (pyin / hpss / chroma /
        tonnetz / piptrack) is SKIPPED and the values from the
        overrides dict are used instead. This is the cycle-1 Review A
        fix: the hot path stays under 20 ms by reading background-
        computed harmonic state.

        If `harmonic_overrides` is None (test callers + the analyze
        CLI subcommand), heavy DSP runs synchronously, preserving the
        full synchronous semantics every prior caller relied on.
        """
        effective_n_fft = max(32, min(self.n_fft, int(y.size)))
        effective_hop_length = max(1, min(self.hop_length, effective_n_fft))
        short_analysis_window = effective_n_fft < self.n_fft

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

            # Mel spectrogram for band energies
            mel = librosa.feature.melspectrogram(
                y=y,
                sr=sr,
                n_fft=effective_n_fft,
                hop_length=effective_hop_length,
                n_mels=self.n_mels,
            )

            # Convert mel bins to approximate frequency bands
            low_bins = int(self.n_mels * 0.1)  # ~0-200 Hz
            mid_bins = int(self.n_mels * 0.5)  # ~200-2000 Hz

            low_energy = float(np.mean(mel[:low_bins, :]))
            mid_energy = float(np.mean(mel[low_bins:mid_bins, :]))
            high_energy = float(np.mean(mel[mid_bins:, :]))

            # ---- HEAVY DSP (synchronous fallback when no overrides) ----
            if harmonic_overrides is not None:
                harmonic_ratio = float(harmonic_overrides.get("harmonic_ratio", 0.5))
                percussive_ratio = float(harmonic_overrides.get("percussive_ratio", 0.5))
                harmonic_change = float(harmonic_overrides.get("harmonic_change", 0.0))
                tonal_stability = float(harmonic_overrides.get("tonal_stability", 0.5))
                harmonic_tension = float(harmonic_overrides.get("harmonic_tension", 0.0))
                pitch_salience = float(harmonic_overrides.get("pitch_salience", 0.0))
                pitch_height = float(harmonic_overrides.get("pitch_height", 0.0))
                melodic_contour = float(harmonic_overrides.get("melodic_contour", 0.5))
                melodic_stability = float(harmonic_overrides.get("melodic_stability", 0.0))
            else:
                # Synchronous full path (test + analyze callers).
                harmonic_spectrum, percussive_spectrum = librosa.decompose.hpss(spectrum, margin=2.0)
                harmonic_energy = float(np.mean(harmonic_spectrum))
                percussive_energy = float(np.mean(percussive_spectrum))
                total_hp_energy = max(harmonic_energy + percussive_energy, 1e-6)
                harmonic_ratio = harmonic_energy / total_hp_energy
                percussive_ratio = percussive_energy / total_hp_energy

                harmonic_change = 0.0
                tonal_stability = 0.0
                harmonic_tension = 0.0
                chroma_std = 0.0
                if not short_analysis_window:
                    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=effective_hop_length)
                    if chroma.shape[1] > 1:
                        chroma_delta = np.abs(np.diff(chroma, axis=1))
                        harmonic_change = float(np.mean(chroma_delta))
                        tonal_stability = float(np.clip(1.0 - (harmonic_change * 1.6), 0.0, 1.0))
                        chroma_std = float(np.std(chroma))

                    harmonic_audio = np.asarray(librosa.effects.harmonic(y), dtype=np.float32)
                    if np.isfinite(harmonic_audio).all():
                        tonnetz = librosa.feature.tonnetz(y=harmonic_audio, sr=sr)
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
                            + (np.clip(chroma_std * 0.65, 0.0, 1.0) * 0.15),
                            0.0,
                            1.0,
                        )
                    )

                # pitch tracking
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

            # ---- LIGHT DSP that depends on light-path values only ----
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
