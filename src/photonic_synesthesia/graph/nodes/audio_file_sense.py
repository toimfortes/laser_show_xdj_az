"""File-backed audio sensor for offline graph playback."""

import time
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np

from photonic_synesthesia.core.logging import get_logger
from photonic_synesthesia.core.state import PhotonicState

logger = get_logger(__name__)

_librosa: Any = None
try:
    import librosa as _librosa_import
except ImportError:
    pass
else:
    _librosa = _librosa_import

librosa: Any = _librosa


class AudioFileSenseNode:
    """Decode an audio file and feed successive chunks into the graph."""

    def __init__(
        self,
        file_path: str | Path,
        *,
        sample_rate: int = 48000,
        chunk_size: int = 1024,
        buffer_seconds: float = 2.0,
    ) -> None:
        self.file_path = Path(file_path)
        self.sample_rate = sample_rate
        self.chunk_size = max(1, int(chunk_size))
        self.buffer_size = max(self.chunk_size, int(buffer_seconds * sample_rate))
        self._buffer: deque[float] = deque(maxlen=self.buffer_size)
        self._samples = np.zeros(0, dtype=np.float32)
        self._position = 0
        self._running = False
        self._error: str | None = None
        self._duration_seconds = 0.0

    def start(self) -> None:
        """Decode the source file and prepare chunk playback."""
        if librosa is None:
            raise RuntimeError("librosa is required for file audio playback")

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
