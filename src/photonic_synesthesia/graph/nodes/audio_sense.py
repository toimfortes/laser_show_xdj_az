"""
Audio Sense Node: Real-time audio capture from USB audio interface.

Captures audio using sounddevice with a callback-based approach for
low-latency operation. Maintains a ring buffer of recent samples.
"""

from __future__ import annotations

import time
from collections import deque

import numpy as np
import structlog
from numpy.typing import NDArray

from photonic_synesthesia.core.config import AudioConfig
from photonic_synesthesia.core.exceptions import AudioCaptureError, AudioDeviceNotFoundError
from photonic_synesthesia.core.state import PhotonicState

logger = structlog.get_logger()

# Import sounddevice conditionally for testing
try:
    import sounddevice as sd

    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    SOUNDDEVICE_AVAILABLE = False
    sd = None


class AudioSenseNode:
    """
    Captures real-time audio and updates state with sample buffer.

    Uses sounddevice's callback interface for low-latency capture.
    The callback runs in a separate high-priority thread managed by PortAudio.
    """

    def __init__(self, config: AudioConfig):
        self.config = config
        self.sample_rate = config.sample_rate
        self.block_size = config.block_size
        self.buffer_size = int(config.buffer_seconds * config.sample_rate)

        # Ring buffer for samples (thread-safe via deque)
        self._buffer: deque[float] = deque(maxlen=self.buffer_size)

        # Stream handle
        self._stream: sd.InputStream | None = None
        self._running = False
        self._error: str | None = None

        # Stats
        self._callback_count = 0
        self._overflows = 0

    def _audio_callback(
        self,
        indata: NDArray[np.float32],
        _frames: int,
        _time_info: dict,
        status: sd.CallbackFlags,
    ) -> None:
        """
        PortAudio callback - runs in dedicated audio thread.

        Must be fast and non-blocking. Only appends to ring buffer.
        """
        if status.input_overflow:
            self._overflows += 1

        # Convert stereo to mono by averaging channels
        if indata.ndim > 1:
            mono = np.mean(indata, axis=1)
        else:
            mono = indata.flatten()

        # Append to ring buffer (deque is thread-safe for append)
        self._buffer.extend(mono.tolist())
        self._callback_count += 1

    def start(self) -> None:
        """Start audio capture stream."""
        if not SOUNDDEVICE_AVAILABLE:
            raise AudioCaptureError(None, "sounddevice not available")

        if self._running:
            return

        logger.info(
            "Starting audio capture",
            device=self.config.device,
            sample_rate=self.sample_rate,
            block_size=self.block_size,
        )

        try:
            # Get device info
            if self.config.device:
                try:
                    device_id = int(self.config.device)
                except ValueError:
                    # Device name - find it
                    devices = sd.query_devices()
                    device_id = None
                    for i, d in enumerate(devices):
                        if self.config.device.lower() in d["name"].lower():
                            device_id = i
                            break
                    if device_id is None:
                        raise AudioDeviceNotFoundError(self.config.device) from None
            else:
                device_id = None  # Use default

            # Create input stream
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                blocksize=self.block_size,
                device=device_id,
                channels=self.config.channels,
                dtype=np.float32,
                callback=self._audio_callback,
                latency=self.config.latency,
            )
            self._stream.start()
            self._running = True
            logger.info("Audio capture started")

        except Exception as e:
            self._error = str(e)
            raise AudioCaptureError(self.config.device, str(e)) from e

    def stop(self) -> None:
        """Stop audio capture stream."""
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self._running = False
        logger.info(
            "Audio capture stopped",
            callbacks=self._callback_count,
            overflows=self._overflows,
        )

    def __call__(self, state: PhotonicState) -> PhotonicState:
        """
        Update state with current audio buffer.

        This is called by the graph - it reads from the ring buffer
        that is being filled by the audio callback.
        """
        state["timestamp"] = time.time()
        state["frame_number"] += 1

        # Copy current buffer contents
        if self._buffer:
            # Get last N samples for analysis
            buffer_list = list(self._buffer)
            state["audio_buffer"] = buffer_list
            state["sample_rate"] = self.sample_rate
            state["sensor_status"]["audio"] = True
        else:
            state["sensor_status"]["audio"] = False

        # Record any errors
        if self._error:
            state["safety_state"]["error_state"] = f"audio: {self._error}"

        return state

    @property
    def is_running(self) -> bool:
        """Check if audio capture is active."""
        return self._running

    def get_stats(self) -> dict:
        """Get capture statistics."""
        return {
            "running": self._running,
            "callbacks": self._callback_count,
            "overflows": self._overflows,
            "buffer_fill": len(self._buffer) / self.buffer_size,
        }
