"""
Configuration Management for Photonic Synesthesia.

Uses Pydantic Settings for type-safe configuration with environment
variable support and YAML file loading.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Dict, List, Any
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
import yaml


class AudioConfig(BaseModel):
    """Audio capture and analysis configuration."""
    device: Optional[str] = None  # None = system default
    sample_rate: int = 48000
    block_size: int = 1024
    channels: int = 2
    buffer_seconds: float = 2.0
    latency: str = "low"  # "low", "high", or float


class MidiConfig(BaseModel):
    """MIDI input configuration."""
    port_name: Optional[str] = None  # None = auto-detect XDJ-AZ
    auto_detect_patterns: List[str] = Field(
        default=["XDJ-AZ", "XDJ-XZ", "DDJ", "Pioneer"]
    )


class CVConfig(BaseModel):
    """Computer vision configuration."""
    enabled: bool = True
    capture_rate_hz: float = 10.0
    bpm_roi: Optional[Dict[str, int]] = None  # x, y, width, height
    waveform_roi: Optional[Dict[str, int]] = None
    lookahead_pixels: int = 50


class DMXConfig(BaseModel):
    """DMX output configuration."""
    interface_type: str = "enttec_open"  # "enttec_open", "enttec_pro", "artnet"
    ftdi_url: str = "ftdi://ftdi:232/1"  # For Enttec Open DMX USB
    serial_port: Optional[str] = None  # For Enttec Pro
    refresh_rate_hz: float = 40.0
    universe: int = 0


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
    cv: CVConfig = Field(default_factory=CVConfig)
    dmx: DMXConfig = Field(default_factory=DMXConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    beat_tracking: BeatTrackingConfig = Field(default_factory=BeatTrackingConfig)
    structure_detection: StructureDetectionConfig = Field(
        default_factory=StructureDetectionConfig
    )
    scene: SceneConfig = Field(default_factory=SceneConfig)

    # Fixtures
    fixtures: List[FixtureConfig] = Field(default_factory=list)

    # Debug
    debug: bool = False
    profile: bool = False
    log_level: str = "INFO"

    class Config:
        env_prefix = "PHOTONIC_"
        env_nested_delimiter = "__"

    @classmethod
    def from_yaml(cls, path: Path) -> "Settings":
        """Load settings from a YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(**data)

    def to_yaml(self, path: Path) -> None:
        """Save settings to a YAML file."""
        with open(path, "w") as f:
            yaml.dump(self.model_dump(), f, default_flow_style=False)


def load_fixture_profile(profile_path: Path) -> Dict[str, Any]:
    """Load a fixture profile from YAML."""
    with open(profile_path) as f:
        return yaml.safe_load(f)


def load_scene(scene_path: Path) -> Dict[str, Any]:
    """Load a scene definition from JSON/YAML."""
    import json

    if scene_path.suffix == ".json":
        with open(scene_path) as f:
            return json.load(f)
    else:
        with open(scene_path) as f:
            return yaml.safe_load(f)
