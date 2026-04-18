from photonic_synesthesia import platform
from photonic_synesthesia.platform import runtime_context as runtime_context_module


def test_runtime_context_public_api_import_smoke() -> None:
    expected = {
        "PlaybackContext",
        "get_shared_control_plane_service",
        "set_shared_control_plane_service",
        "clear_shared_control_plane_service",
        "get_shared_playback_context",
        "set_shared_playback_context",
        "clear_shared_playback_context",
    }

    for name in expected:
        assert hasattr(runtime_context_module, name)

    assert runtime_context_module.get_shared_playback_context() is None


def test_platform_reexports_runtime_context_public_api() -> None:
    assert platform.PlaybackContext is runtime_context_module.PlaybackContext
    assert platform.get_shared_playback_context is runtime_context_module.get_shared_playback_context
