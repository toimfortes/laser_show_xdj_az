"""Regression tests for E7: audio_file_sense memory bounds (H6 + M2).

Pre-E7:
  - `librosa.load` decoded the whole file into RAM. A 4h 48kHz mono
    float32 capture = 2.7 GB; a stereo 8h studio session = 11 GB.
    Operator pointing at the wrong file OOMs the host before
    playback even starts.
  - `buffer_seconds <= 0` (operator typo) silently produced
    `deque(maxlen=-1)` which is unbounded — over time the audio
    buffer grows without limit.

E7:
  - Hard duration cap (default 8h) checked via `soundfile.info`
    BEFORE `librosa.load` runs. Refuses with `AudioCaptureError`.
  - Constructor refuses non-positive `chunk_size`, `buffer_seconds`,
    `sample_rate`, `max_duration_seconds`.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import numpy as np
import pytest

from photonic_synesthesia.core.exceptions import AudioCaptureError
from photonic_synesthesia.graph.nodes.audio_file_sense import AudioFileSenseNode


def test_constructor_refuses_negative_buffer_seconds() -> None:
    """M2: pre-E7 a negative buffer_seconds produced deque(maxlen<0)
    which is unbounded. Now it raises at construction time."""
    with pytest.raises(ValueError, match="buffer_seconds must be positive"):
        AudioFileSenseNode("/dev/null", buffer_seconds=-1.0)


def test_constructor_refuses_zero_chunk_size() -> None:
    with pytest.raises(ValueError, match="chunk_size must be positive"):
        AudioFileSenseNode("/dev/null", chunk_size=0)


def test_constructor_refuses_negative_sample_rate() -> None:
    with pytest.raises(ValueError, match="sample_rate must be positive"):
        AudioFileSenseNode("/dev/null", sample_rate=-1)


def test_constructor_refuses_zero_max_duration() -> None:
    with pytest.raises(ValueError, match="max_duration_seconds must be positive"):
        AudioFileSenseNode("/dev/null", max_duration_seconds=0)


def test_start_refuses_overlong_file_before_decoding(tmp_path: Path) -> None:
    """H6 invariant: a multi-hour file MUST be refused via cheap
    soundfile.info() probe BEFORE librosa.load fully decodes it
    into RAM. We confirm by:
      1. Patching soundfile.info to claim a 10-hour file.
      2. Patching librosa.load to fail loudly if called.
      3. Asserting AudioCaptureError is raised."""
    fake_path = tmp_path / "long.wav"
    fake_path.write_bytes(b"")  # contents irrelevant; we mock info+load

    fake_info = mock.MagicMock()
    fake_info.frames = 48000 * 60 * 60 * 10  # 10 hours
    fake_info.samplerate = 48000

    librosa_was_called = {"value": False}

    def _fail_if_called(*args, **kwargs):
        librosa_was_called["value"] = True
        raise AssertionError("librosa.load must NOT be reached for overlong files")

    node = AudioFileSenseNode(
        fake_path,
        sample_rate=48000,
        max_duration_seconds=8 * 3600.0,  # 8h cap
    )

    with (
        mock.patch(
            "photonic_synesthesia.graph.nodes.audio_file_sense.soundfile.info",
            return_value=fake_info,
        ),
        mock.patch(
            "photonic_synesthesia.graph.nodes.audio_file_sense.librosa.load",
            side_effect=_fail_if_called,
        ),
    ):
        with pytest.raises(AudioCaptureError, match="exceeds max_duration_seconds"):
            node.start()

    assert not librosa_was_called["value"], (
        "H6 fix failed: librosa.load was reached even though file exceeds cap"
    )


def test_start_succeeds_for_file_under_max_duration(tmp_path: Path) -> None:
    """Sanity: a normal (~5 second) file decodes cleanly when under
    the duration cap."""
    fake_path = tmp_path / "short.wav"
    fake_path.write_bytes(b"")

    fake_info = mock.MagicMock()
    fake_info.frames = 48000 * 5  # 5 seconds
    fake_info.samplerate = 48000

    fake_samples = np.zeros(48000 * 5, dtype=np.float32)

    node = AudioFileSenseNode(fake_path, sample_rate=48000)

    with (
        mock.patch(
            "photonic_synesthesia.graph.nodes.audio_file_sense.soundfile.info",
            return_value=fake_info,
        ),
        mock.patch(
            "photonic_synesthesia.graph.nodes.audio_file_sense.librosa.load",
            return_value=(fake_samples, 48000),
        ),
    ):
        node.start()

    assert node._running
    assert node.duration_seconds == pytest.approx(5.0)


def test_start_with_max_duration_none_skips_check(tmp_path: Path) -> None:
    """Opt-out path: explicit `max_duration_seconds=None` skips the
    pre-decode duration probe entirely."""
    fake_path = tmp_path / "long.wav"
    fake_path.write_bytes(b"")

    fake_samples = np.zeros(48000 * 10, dtype=np.float32)

    info_call_count = {"n": 0}

    def _track_info(*args, **kwargs):
        info_call_count["n"] += 1
        return mock.MagicMock(frames=48000 * 10, samplerate=48000)

    node = AudioFileSenseNode(fake_path, sample_rate=48000, max_duration_seconds=None)

    with (
        mock.patch(
            "photonic_synesthesia.graph.nodes.audio_file_sense.soundfile.info",
            side_effect=_track_info,
        ),
        mock.patch(
            "photonic_synesthesia.graph.nodes.audio_file_sense.librosa.load",
            return_value=(fake_samples, 48000),
        ),
    ):
        node.start()

    # With max_duration_seconds=None, soundfile.info MUST NOT be called.
    assert info_call_count["n"] == 0, (
        "max_duration_seconds=None should skip the pre-decode probe"
    )
    assert node._running
