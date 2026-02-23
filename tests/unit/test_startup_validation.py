from pathlib import Path

import pytest

from photonic_synesthesia.core.config import FixtureConfig, SceneConfig, Settings
from photonic_synesthesia.core.exceptions import ConfigError, FixtureProfileError, SceneError
from photonic_synesthesia.ui.cli import _validate_startup_config


def test_startup_validation_rejects_missing_fixture_profile() -> None:
    settings = Settings(
        fixtures=[
            FixtureConfig(
                id="laser1",
                name="Laser 1",
                type="laser",
                profile="does_not_exist",
                start_address=1,
                enabled=True,
            )
        ]
    )

    with pytest.raises(FixtureProfileError):
        _validate_startup_config(settings, mock=False)


def test_startup_validation_rejects_fixture_spanning_beyond_512() -> None:
    settings = Settings(
        fixtures=[
            FixtureConfig(
                id="laser1",
                name="Laser 1",
                type="laser",
                profile="laser_generic_7ch",
                start_address=510,
                enabled=True,
            )
        ]
    )

    with pytest.raises(ConfigError):
        _validate_startup_config(settings, mock=False)


def test_startup_validation_rejects_missing_non_idle_default_scene(tmp_path: Path) -> None:
    settings = Settings(
        scene=SceneConfig(scenes_dir=tmp_path, default_scene="peak_scene"),
        fixtures=[],
    )

    with pytest.raises(SceneError):
        _validate_startup_config(settings, mock=True)


def test_startup_validation_allows_valid_single_fixture_config() -> None:
    settings = Settings(
        fixtures=[
            FixtureConfig(
                id="laser1",
                name="Laser 1",
                type="laser",
                profile="laser_generic_7ch",
                start_address=1,
                enabled=True,
            )
        ]
    )

    _validate_startup_config(settings, mock=False)
