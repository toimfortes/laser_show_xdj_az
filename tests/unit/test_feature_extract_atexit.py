"""Regression tests for FeatureExtractNode atexit cleanup."""

from __future__ import annotations

from unittest import mock


def test_harmonic_analyzer_atexit_hook_is_defined() -> None:
    from photonic_synesthesia.graph.nodes import feature_extract

    assert hasattr(feature_extract, "_shutdown_harmonic_analyzers_at_exit")
    assert callable(feature_extract._shutdown_harmonic_analyzers_at_exit)


def test_harmonic_analyzer_atexit_closes_registered_instances() -> None:
    from photonic_synesthesia.graph.nodes import feature_extract

    analyzer = feature_extract._HarmonicAnalyzer(n_fft=1024, hop_length=256)
    try:
        with mock.patch.object(analyzer, "close") as close_mock:
            feature_extract._shutdown_harmonic_analyzers_at_exit()
        assert close_mock.called, "atexit hook must close registered harmonic analyzers"
    finally:
        analyzer.close()

