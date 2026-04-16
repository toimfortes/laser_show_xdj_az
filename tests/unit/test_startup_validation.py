from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from photonic_synesthesia.core.config import FixtureConfig, ILDAConfig, SceneConfig, Settings
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


def test_startup_validation_rejects_unverified_hybrid_laser_in_live_mode() -> None:
    settings = Settings(
        fixtures=[
            FixtureConfig(
                id="laser-main",
                name="Main Festival Laser",
                type="laser",
                profile="laser_aucd_cx338b_hybrid",
                start_address=1,
                enabled=True,
            )
        ]
    )

    with pytest.raises(FixtureProfileError):
        _validate_startup_config(settings, mock=False)


def test_startup_validation_allows_unverified_hybrid_laser_with_override() -> None:
    settings = Settings(
        fixtures=[
            FixtureConfig(
                id="laser-main",
                name="Main Festival Laser",
                type="laser",
                profile="laser_aucd_cx338b_hybrid",
                start_address=1,
                enabled=True,
            )
        ]
    )
    settings.runtime_flags.allow_unverified_laser_profiles = True

    _validate_startup_config(settings, mock=False)


def test_startup_validation_rejects_unreachable_ether_dream_transport() -> None:
    settings = Settings(
        fixtures=[
            FixtureConfig(
                id="laser-main",
                name="Main Festival Laser",
                type="laser",
                profile="laser_aucd_cx338b_hybrid",
                start_address=1,
                enabled=True,
            )
        ],
        ilda=ILDAConfig(
            enabled=True,
            transport_type="ether_dream",
            ether_dream_host="192.0.2.10",
            ether_dream_port=7765,
            ether_dream_timeout_s=0.25,
        ),
    )
    settings.runtime_flags.allow_unverified_laser_profiles = True

    with patch("photonic_synesthesia.ui.cli.socket.create_connection", side_effect=OSError("timed out")):
        with pytest.raises(ConfigError, match="Ether Dream DAC is not reachable"):
            _validate_startup_config(settings, mock=False)


def test_startup_validation_accepts_reachable_ether_dream_transport() -> None:
    settings = Settings(
        fixtures=[
            FixtureConfig(
                id="laser-main",
                name="Main Festival Laser",
                type="laser",
                profile="laser_aucd_cx338b_hybrid",
                start_address=1,
                enabled=True,
            )
        ],
        ilda=ILDAConfig(
            enabled=True,
            transport_type="ether_dream",
            ether_dream_host="192.0.2.10",
            ether_dream_port=7765,
            ether_dream_timeout_s=0.25,
        ),
    )
    settings.runtime_flags.allow_unverified_laser_profiles = True

    fake_socket = MagicMock()
    fake_socket.__enter__.return_value = fake_socket
    fake_socket.__exit__.return_value = False

    with patch("photonic_synesthesia.ui.cli.socket.create_connection", return_value=fake_socket) as create_connection:
        _validate_startup_config(settings, mock=False)

    create_connection.assert_called_once_with(("192.0.2.10", 7765), timeout=0.25)
