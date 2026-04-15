import math
import wave
from pathlib import Path

from photonic_synesthesia.core.state import create_initial_state
from photonic_synesthesia.graph.nodes.audio_file_sense import AudioFileSenseNode


def _write_test_wave(path: Path, *, sample_rate: int = 8000, duration_s: float = 0.25) -> None:
    frame_count = int(sample_rate * duration_s)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)

        frames = bytearray()
        for index in range(frame_count):
            sample = int(32767 * math.sin(2.0 * math.pi * 220.0 * index / sample_rate))
            frames.extend(int(sample).to_bytes(2, byteorder="little", signed=True))
        handle.writeframes(bytes(frames))


def test_audio_file_sense_streams_chunks_from_decoded_file(tmp_path: Path) -> None:
    audio_path = tmp_path / "fixture.wav"
    _write_test_wave(audio_path)

    node = AudioFileSenseNode(audio_path, sample_rate=8000, chunk_size=400, buffer_seconds=0.2)
    state = create_initial_state()

    node.start()

    observed_lengths: list[int] = []
    while not node.finished:
        state = node(state)
        observed_lengths.append(len(state["audio_buffer"]))

    assert state["sensor_status"]["audio"] is True
    assert observed_lengths[0] == 400
    assert max(observed_lengths) <= 1600
    assert node.playhead_seconds == node.duration_seconds

    node.stop()
