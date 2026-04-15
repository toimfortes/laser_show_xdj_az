from photonic_synesthesia.core.config import RuntimeFlagsConfig, Settings


def test_runtime_flags_defaults() -> None:
    flags = RuntimeFlagsConfig()
    assert flags.cv_threaded is True
    assert flags.dmx_double_buffer is True
    assert flags.hybrid_pacing is True
    assert flags.streaming_dsp is False
    assert flags.dual_loop is False


def test_settings_exposes_runtime_flags() -> None:
    settings = Settings()
    assert settings.runtime_flags.cv_threaded is True
    assert settings.runtime_flags.dmx_double_buffer is True
