"""File-backed audio sensor for offline graph playback."""

import time
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np

from photonic_synesthesia.core.exceptions import AudioCaptureError
from photonic_synesthesia.core.logging import get_logger
from photonic_synesthesia.core.state import PhotonicState

logger = get_logger(__name__)

# Cycle-6 E7/H6: hard duration cap so an operator pointing at a
# multi-hour studio session capture doesn't OOM the host. 8h × 48kHz
# × 4B (mono float32) = ~5.5 GB. Generous enough for any DJ set;
# tight enough to refuse "I dragged the wrong file" mistakes. Override
# via constructor arg.
_DEFAULT_MAX_DURATION_SECONDS: float = 8.0 * 3600.0

_librosa: Any = None
try:
    import librosa as _librosa_import
except ImportError:
    pass
else:
    _librosa = _librosa_import

librosa: Any = _librosa

_soundfile: Any = None
try:
    import soundfile as _soundfile_import
except ImportError:
    pass
else:
    _soundfile = _soundfile_import

soundfile: Any = _soundfile


class AudioFileSenseNode:
    """Decode an audio file and feed successive chunks into the graph."""

    def __init__(
        self,
        file_path: str | Path,
        *,
        sample_rate: int = 48000,
        chunk_size: int = 1024,
        buffer_seconds: float = 2.0,
        max_duration_seconds: float | None = _DEFAULT_MAX_DURATION_SECONDS,
    ) -> None:
        # Cycle-6 E7/M2: assert the buffer is positive. Pre-E7 a
        # negative `buffer_seconds` (operator typo) would compute
        # `max(1024, -N)` = 1024 (saved by the chunk_size floor) but
        # we still want a loud failure on the boundary case
        # buffer_seconds=0 + chunk_size=0 → deque(maxlen=0) silently
        # drops everything. Better to refuse outright.
        if int(chunk_size) <= 0:
            raise ValueError(f"chunk_size must be positive; got {chunk_size}")
        if buffer_seconds <= 0:
            raise ValueError(f"buffer_seconds must be positive; got {buffer_seconds}")
        if sample_rate <= 0:
            raise ValueError(f"sample_rate must be positive; got {sample_rate}")
        if max_duration_seconds is not None and max_duration_seconds <= 0:
            raise ValueError(
                f"max_duration_seconds must be positive or None; got {max_duration_seconds}"
            )

        self.file_path = Path(file_path)
        self.sample_rate = sample_rate
        self.chunk_size = int(chunk_size)
        self.buffer_size = max(self.chunk_size, int(buffer_seconds * sample_rate))
        self.max_duration_seconds = max_duration_seconds
        self._buffer: deque[float] = deque(maxlen=self.buffer_size)
        self._samples = np.zeros(0, dtype=np.float32)
        self._position = 0
        self._running = False
        self._error: str | None = None
        self._duration_seconds = 0.0

    def start(self) -> None:
        """Decode the source file and prepare chunk playback.

        Cycle-6 E7/H6: query the file's duration via `soundfile.info`
        BEFORE calling `librosa.load` so a multi-hour file can be
        refused without first decoding 1-5 GB into RAM. The default
        cap is 8 hours (~5.5 GB at 48kHz mono float32); pass
        `max_duration_seconds=None` at construction to opt out.
        """
        if self._running and self._samples.size > 0:
            return
        if librosa is None:
            raise RuntimeError("librosa is required for file audio playback")

        # Pre-decode duration check (E7/H6).
        if self.max_duration_seconds is not None and soundfile is not None:
            try:
                info = soundfile.info(str(self.file_path))
                samplerate = float(info.samplerate or 0)
                if samplerate <= 0:
                    raise ValueError(f"invalid samplerate from probe: {samplerate!r}")
                source_duration_s = float(info.frames) / samplerate
            except Exception as exc:
                logger.warning("audio_file_duration_probe_failed", error=str(exc))
                raise AudioCaptureError(
                    str(self.file_path),
                    (
                        "could not determine duration before decode; refusing to load "
                        "while max_duration_seconds is enforced. Pass "
                        "max_duration_seconds=None to override."
                    ),
                ) from exc
            if source_duration_s > self.max_duration_seconds:
                raise AudioCaptureError(
                    str(self.file_path),
                    (
                        f"file is {source_duration_s:.0f}s long, exceeds "
                        f"max_duration_seconds={self.max_duration_seconds:.0f}s. "
                        f"Decoding the whole file would consume "
                        f"~{int(source_duration_s * self.sample_rate * 4 / (1024**3))} GB. "
                        f"Pass max_duration_seconds=None to override."
                    ),
                )
        elif self.max_duration_seconds is not None and soundfile is None:
            raise AudioCaptureError(
                str(self.file_path),
                (
                    "could not determine duration before decode because soundfile is "
                    "unavailable; refusing to load while max_duration_seconds is "
                    "enforced. Pass max_duration_seconds=None to override."
                ),
            )

        logger.info(
            "Loading audio file",
            file_path=str(self.file_path),
            sample_rate=self.sample_rate,
            chunk_size=self.chunk_size,
        )
        samples, sample_rate = librosa.load(
            str(self.file_path),
            sr=self.sample_rate,
            mono=True,
        )
        self._samples = np.asarray(samples, dtype=np.float32)
        self.sample_rate = int(sample_rate)
        self._position = 0
        self._buffer.clear()
        self._running = True
        self._error = None
        self._duration_seconds = (
            float(len(self._samples)) / float(self.sample_rate) if self.sample_rate > 0 else 0.0
        )

    def stop(self) -> None:
        """Stop file playback."""
        self._running = False
        logger.info(
            "Audio file playback stopped",
            file_path=str(self.file_path),
            playhead_seconds=self.playhead_seconds,
            duration_seconds=self.duration_seconds,
        )

    def seek(self, position_seconds: float) -> float:
        """Seek playback to an absolute position in seconds."""
        if self.sample_rate <= 0 or self._samples.size == 0:
            return 0.0
        target_seconds = max(0.0, min(float(position_seconds), self.duration_seconds))
        target_index = min(len(self._samples), max(0, int(target_seconds * self.sample_rate)))
        self._position = target_index
        self._buffer.clear()
        if target_index >= len(self._samples):
            self._running = False
        else:
            self._running = True
        logger.info(
            "Audio file playback seeked",
            file_path=str(self.file_path),
            playhead_seconds=self.playhead_seconds,
            duration_seconds=self.duration_seconds,
        )
        return self.playhead_seconds

    def __call__(self, state: PhotonicState) -> PhotonicState:
        """Append the next decoded chunk to the rolling analysis buffer."""
        state["timestamp"] = time.time()
        state["frame_number"] += 1
        state["sample_rate"] = self.sample_rate

        if not self._running or self._error is not None:
            state["sensor_status"]["audio"] = False
            if self._error:
                state["safety_state"]["error_state"] = f"audio_file: {self._error}"
            return state

        end = min(self._position + self.chunk_size, len(self._samples))
        chunk = self._samples[self._position:end]
        self._position = end

        if chunk.size > 0:
            self._buffer.extend(chunk.tolist())
            state["audio_buffer"] = list(self._buffer)
            state["sensor_status"]["audio"] = True
        else:
            state["sensor_status"]["audio"] = False

        if self._position >= len(self._samples):
            self._running = False

        return state

    @property
    def finished(self) -> bool:
        """Whether the full file has been consumed."""
        return self._position >= len(self._samples)

    @property
    def playhead_seconds(self) -> float:
        """Current decoded playback position in seconds."""
        if self.sample_rate <= 0:
            return 0.0
        return float(self._position) / float(self.sample_rate)

    @property
    def duration_seconds(self) -> float:
        """Total duration of the decoded source in seconds."""
        return self._duration_seconds

    def waveform_preview(self, bins: int = 256) -> list[float]:
        """Return normalized peak values for lightweight waveform rendering."""
        if self._samples.size == 0 or bins <= 0:
            return []

        window = max(1, len(self._samples) // bins)
        peaks: list[float] = []
        for start in range(0, len(self._samples), window):
            chunk = self._samples[start : start + window]
            if chunk.size == 0:
                continue
            peaks.append(float(np.max(np.abs(chunk))))

        if not peaks:
            return []
        scale = max(peaks) or 1.0
        return [round(value / scale, 4) for value in peaks[:bins]]
