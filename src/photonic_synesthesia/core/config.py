"""
Configuration Management for Photonic Synesthesia.

Uses Pydantic Settings for type-safe configuration with environment
variable support and YAML file loading.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class AudioConfig(BaseModel):
    """Audio capture and analysis configuration."""

    device: str | None = None  # None = system default
    sample_rate: int = 48000
    block_size: int = 1024
    channels: int = 2
    buffer_seconds: float = 2.0
    latency: str = "low"  # "low", "high", or float


class MidiConfig(BaseModel):
    """MIDI input configuration."""

    port_name: str | None = None  # None = auto-detect XDJ-AZ
    auto_detect_patterns: list[str] = Field(default=["XDJ-AZ", "XDJ-XZ", "DDJ", "Pioneer"])


class ProDJLinkConfig(BaseModel):
    """PRO DJ LINK network telemetry configuration."""

    enabled: bool = False
    listen_host: str = "127.0.0.1"
    keepalive_port: int = 50000
    status_port: int = 50001
    beat_port: int = 50002


class CVConfig(BaseModel):
    """Computer vision configuration."""

    enabled: bool = True
    capture_rate_hz: float = 10.0
    bpm_roi: dict[str, int] | None = None  # x, y, width, height
    waveform_roi: dict[str, int] | None = None
    lookahead_pixels: int = 50


class DMXConfig(BaseModel):
    """DMX output configuration."""

    interface_type: str = "enttec_open"  # "enttec_open", "enttec_pro", "artnet"
    ftdi_url: str = "ftdi://ftdi:232/1"  # For Enttec Open DMX USB
    serial_port: str | None = None  # For Enttec Pro
    refresh_rate_hz: float = 40.0
    universe: int = 0
    artnet_host: str = "255.255.255.255"
    artnet_port: int = 6454
    artnet_broadcast: bool = True
    artnet_net: int = 0
    artnet_subnet: int = 0


class FixtureConfig(BaseModel):
    """Individual fixture configuration."""

    id: str
    name: str
    type: str  # "laser", "moving_head", "panel"
    profile: str  # Reference to profile YAML
    start_address: int
    enabled: bool = True


class LaserSafetyConfig(BaseModel):
    """Laser-specific safety limits."""

    y_axis_max: int = 100  # Max tilt value to prevent crowd scanning
    min_scan_speed: int = 30
    y_channel_offset: int = 3
    speed_channel_offset: int = 4
    max_intensity_no_movement: int = 50
    enable_delay_ms: int = 500


class StrobeSafetyConfig(BaseModel):
    """Strobe safety limits."""

    max_rate_hz: float = 10.0
    max_duration_s: float = 5.0
    cooldown_s: float = 2.0


class MovingHeadSafetyConfig(BaseModel):
    """Moving head safety limits."""

    max_pan_speed: int = 200
    max_tilt_speed: int = 200
    home_on_error: bool = True


class SafetyConfig(BaseModel):
    """Safety system configuration."""

    laser: LaserSafetyConfig = Field(default_factory=LaserSafetyConfig)
    strobe: StrobeSafetyConfig = Field(default_factory=StrobeSafetyConfig)
    moving_head: MovingHeadSafetyConfig = Field(default_factory=MovingHeadSafetyConfig)
    heartbeat_timeout_s: float = 1.0
    analysis_timeout_s: float = 2.0
    min_beat_confidence: float = 0.3
    graceful_degradation: bool = True


class BeatTrackingConfig(BaseModel):
    """Beat tracking configuration."""

    backend: str = "madmom"  # "madmom", "beatnet"
    online_mode: bool = True
    confidence_threshold: float = 0.5


class StructureDetectionConfig(BaseModel):
    """Structure detection (drop/buildup) configuration."""

    drop_rms_multiplier: float = 2.0
    buildup_slope_threshold: float = 0.01
    gap_rms_threshold: float = 0.3
    min_drop_interval_s: float = 10.0


class SceneConfig(BaseModel):
    """Scene management configuration."""

    scenes_dir: Path = Path("config/scenes")
    default_scene: str = "idle"
    transition_time_s: float = 0.5


class Settings(BaseSettings):
    """
    Main application settings.

    Can be configured via:
    - Environment variables (prefixed with PHOTONIC_)
    - YAML config file
    - Direct instantiation
    """

    # Paths
    config_dir: Path = Path("config")
    fixtures_dir: Path = Path("config/fixtures")
    scenes_dir: Path = Path("config/scenes")

    # Component configs
    audio: AudioConfig = Field(default_factory=AudioConfig)
    midi: MidiConfig = Field(default_factory=MidiConfig)
    pro_dj_link: ProDJLinkConfig = Field(default_factory=ProDJLinkConfig)
    cv: CVConfig = Field(default_factory=CVConfig)
    dmx: DMXConfig = Field(default_factory=DMXConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    beat_tracking: BeatTrackingConfig = Field(default_factory=BeatTrackingConfig)
    structure_detection: StructureDetectionConfig = Field(default_factory=StructureDetectionConfig)
    scene: SceneConfig = Field(default_factory=SceneConfig)

    # Fixtures
    fixtures: list[FixtureConfig] = Field(default_factory=list)

    # Debug
    debug: bool = False
    profile: bool = False
    log_level: str = "INFO"

    class Config:
        env_prefix = "PHOTONIC_"
        env_nested_delimiter = "__"

    @classmethod
    def from_yaml(cls, path: Path) -> Settings:
        """Load settings from a YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(**data)

    def to_yaml(self, path: Path) -> None:
        """Save settings to a YAML file."""
        with open(path, "w") as f:
            yaml.dump(self.model_dump(), f, default_flow_style=False)


def load_fixture_profile(profile_path: Path) -> dict[str, Any]:
    """Load a fixture profile from YAML."""
    with open(profile_path) as f:
        return cast(dict[str, Any], yaml.safe_load(f))


def load_scene(scene_path: Path) -> dict[str, Any]:
    """Load a scene definition from JSON/YAML."""
    import json

    if scene_path.suffix == ".json":
        with open(scene_path) as f:
            return cast(dict[str, Any], json.load(f))
    else:
        with open(scene_path) as f:
            return cast(dict[str, Any], yaml.safe_load(f))
