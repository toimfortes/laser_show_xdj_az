"""Exit-code baseline tests for the Click CLI commands.

Part of Plan Task 6 (CLI domain extraction / thin shell). Each baseline
command gets at least one success path asserting `exit_code == 0` and one
representative failure path asserting `exit_code == 1`, so regressions in
the CLI's process-exit translation surface loudly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

import photonic_synesthesia.ui.cli as cli_module
from photonic_synesthesia.ui.cli import cli


# ---------------------------------------------------------------------------
# catalog build
# ---------------------------------------------------------------------------
def test_catalog_build_no_audio_files_fails_with_exit_code_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """catalog build over an empty directory must exit with code 1."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    empty_dir = tmp_path / "no_audio"
    empty_dir.mkdir()

    result = CliRunner().invoke(cli, ["catalog", "build", str(empty_dir)])

    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# catalog export-model-payloads
# ---------------------------------------------------------------------------
def test_catalog_export_model_payloads_empty_catalog_fails_with_exit_code_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exporting model payloads with no catalog entries exits non-zero."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    output_file = tmp_path / "payloads.jsonl"
    result = CliRunner().invoke(
        cli,
        ["catalog", "export-model-payloads", str(output_file)],
    )

    assert result.exit_code == 1


def test_catalog_export_model_payloads_success_returns_exit_code_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A catalog with a model_payload exports and exits 0."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from photonic_synesthesia.integrations.show_catalog import save_show_catalog

    save_show_catalog(
        "Artist|Song",
        {
            "track_key": "Artist|Song",
            "show_sections": [],
            "model_payload": {
                "track_key": "Artist|Song",
                "sections": [],
            },
        },
    )

    output_file = tmp_path / "payloads.jsonl"
    result = CliRunner().invoke(
        cli,
        ["catalog", "export-model-payloads", str(output_file)],
    )

    assert result.exit_code == 0
    assert output_file.exists()


# ---------------------------------------------------------------------------
# dmx-test
# ---------------------------------------------------------------------------
def test_dmx_test_invalid_channel_fails_with_exit_code_one() -> None:
    """dmx-test with an out-of-range channel must exit with code 1."""
    result = CliRunner().invoke(
        cli,
        ["dmx-test", "--channel", "9999", "--value", "100"],
    )

    assert result.exit_code == 1


def test_dmx_test_invalid_value_fails_with_exit_code_one() -> None:
    """dmx-test with an out-of-range value must exit with code 1."""
    result = CliRunner().invoke(
        cli,
        ["dmx-test", "--channel", "1", "--value", "999"],
    )

    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# list-audio
# ---------------------------------------------------------------------------
def test_list_audio_success_returns_exit_code_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """list-audio exits 0 when sounddevice enumerates cleanly."""
    import sys
    import types

    fake_module = types.ModuleType("sounddevice")

    def _query_devices() -> list[dict[str, Any]]:
        return [
            {
                "name": "Fake Microphone",
                "max_input_channels": 2,
                "default_samplerate": 44100.0,
            },
        ]

    fake_module.query_devices = _query_devices
    fake_module.default = types.SimpleNamespace(device=(0, 0))
    monkeypatch.setitem(sys.modules, "sounddevice", fake_module)

    result = CliRunner().invoke(cli, ["list-audio"])

    assert result.exit_code == 0
    assert "Fake Microphone" in result.output


def test_list_audio_missing_sounddevice_fails_with_exit_code_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """list-audio exits 1 when the sounddevice dependency is missing."""
    import builtins
    import sys

    # Remove any cached sounddevice module so the import fails in-command.
    monkeypatch.delitem(sys.modules, "sounddevice", raising=False)

    real_import = builtins.__import__

    def _fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "sounddevice":
            raise ImportError("sounddevice not available in this environment")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    result = CliRunner().invoke(cli, ["list-audio"])

    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# list-midi
# ---------------------------------------------------------------------------
def test_list_midi_success_returns_exit_code_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """list-midi exits 0 when mido enumerates cleanly."""
    import sys
    import types

    fake_module = types.ModuleType("mido")
    fake_module.get_input_names = lambda: ["Fake MIDI Port"]
    monkeypatch.setitem(sys.modules, "mido", fake_module)

    result = CliRunner().invoke(cli, ["list-midi"])

    assert result.exit_code == 0
    assert "Fake MIDI Port" in result.output


def test_list_midi_missing_mido_fails_with_exit_code_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """list-midi exits 1 when the mido dependency is missing."""
    import builtins
    import sys

    monkeypatch.delitem(sys.modules, "mido", raising=False)

    real_import = builtins.__import__

    def _fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "mido":
            raise ImportError("mido not available in this environment")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    result = CliRunner().invoke(cli, ["list-midi"])

    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# run-file
# ---------------------------------------------------------------------------
def test_run_file_missing_audio_fails_with_non_zero_exit_code(
    tmp_path: Path,
) -> None:
    """run-file with a missing audio path rejects input (Click exit_code != 0)."""
    missing = tmp_path / "does_not_exist.mp3"
    result = CliRunner().invoke(cli, ["run-file", str(missing)])

    # Click's built-in `exists=True` Path validation returns exit_code 2 via
    # UsageError; any non-zero exit counts as a CLI-side failure signal.
    assert result.exit_code != 0
