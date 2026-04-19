"""FastAPI-based control plane for the optional web interface."""

import asyncio
import copy
import math
import os
import random
import socket
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

# pydantic is a core dependency, so BaseModel is always importable. Only
# the fastapi/uvicorn stack is optional, so that import still goes
# through _import_web_stack() below.
from pydantic import BaseModel

from photonic_synesthesia import __version__
from photonic_synesthesia.platform import (
    CommandType,
    ControlPlaneStateService,
    LeaseAcquireRequest,
    OperatorCommand,
    OperatorRole,
    PlatformEventType,
    PlaybackContext,
    get_shared_control_plane_service,
    get_shared_playback_context,
)

MOCK_FIXTURE_TEMPLATES: list[dict[str, Any]] = [
    {
        "slug": "laser",
        "label": "Laser Scanner",
        "type": "laser",
        "description": "Multi-beam fan with wide scan spread and fast rhythmic motion.",
        "defaults": {
            "color": "#12d8ff",
            "intensity": 0.9,
            "x": 0.18,
            "y": 0.16,
            "spread": 0.30,
            "beam_count": 5,
            "swing": 0.40,
            "universe": 1,
            "address": 1,
        },
    },
    {
        "slug": "moving_head",
        "label": "Moving Head",
        "type": "moving_head",
        "description": "Pan/tilt spot with beam cone, sweep range, and target motion.",
        "defaults": {
            "color": "#ff7a18",
            "intensity": 0.8,
            "x": 0.42,
            "y": 0.12,
            "pan": 0.0,
            "tilt": 0.55,
            "pan_range": 0.55,
            "tilt_range": 0.35,
            "beam_width": 0.10,
            "universe": 1,
            "address": 30,
        },
    },
    {
        "slug": "wash",
        "label": "Wash Fixture",
        "type": "wash",
        "description": "Soft color field for stage coverage and scene mood.",
        "defaults": {
            "color": "#ff4d6d",
            "intensity": 0.65,
            "x": 0.68,
            "y": 0.20,
            "radius": 0.22,
            "universe": 1,
            "address": 60,
        },
    },
    {
        "slug": "led_bar",
        "label": "LED Bar",
        "type": "led_bar",
        "description": "Pixel strip style bar for chases, accents, and audience wash.",
        "defaults": {
            "color": "#7cf29c",
            "intensity": 0.75,
            "x": 0.84,
            "y": 0.18,
            "pixel_count": 6,
            "width": 0.18,
            "universe": 1,
            "address": 90,
        },
    },
]

MOCK_SCENE_TEMPLATES: list[dict[str, Any]] = [
    {
        "scene_id": "intro_ambient",
        "label": "Intro Ambient",
        "palette": ["#12d8ff", "#ffc857", "#ff7a18"],
        "speed_multiplier": 0.55,
        "pulse": 0.35,
        "strobe": 0.0,
    },
    {
        "scene_id": "break_sweep",
        "label": "Break Sweep",
        "palette": ["#0ea5e9", "#f97316", "#fb7185"],
        "speed_multiplier": 0.9,
        "pulse": 0.5,
        "strobe": 0.05,
    },
    {
        "scene_id": "drop_intense",
        "label": "Drop Intense",
        "palette": ["#f94144", "#f8961e", "#90be6d"],
        "speed_multiplier": 1.4,
        "pulse": 0.85,
        "strobe": 0.18,
    },
]

MOCK_DEFAULT_RIG: list[dict[str, Any]] = [
    {"template": "laser", "label": "Laser A"},
    {"template": "moving_head", "label": "Mover A"},
    {"template": "moving_head", "label": "Mover B"},
    {"template": "wash", "label": "Wash A"},
    {"template": "led_bar", "label": "Bar A"},
]

_FIXTURE_TEMPLATE_INDEX = {item["slug"]: item for item in MOCK_FIXTURE_TEMPLATES}
_SCENE_TEMPLATE_INDEX = {item["scene_id"]: item for item in MOCK_SCENE_TEMPLATES}


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _normalize_float(value: Any, lower: float, upper: float) -> float:
    return _clamp(float(value), lower, upper)


def _normalize_int(value: Any, lower: int, upper: int) -> int:
    return max(lower, min(upper, int(value)))


def _normalize_color(value: Any) -> str:
    text = str(value).strip()
    if not text.startswith("#"):
        text = f"#{text}"
    if len(text) == 4:
        text = "#" + "".join(char * 2 for char in text[1:])
    if len(text) != 7:
        return "#ffffff"
    try:
        int(text[1:], 16)
    except ValueError:
        return "#ffffff"
    return text.lower()


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    normalized = _normalize_color(hex_color)
    value = int(normalized[1:], 16)
    return ((value >> 16) & 255, (value >> 8) & 255, value & 255)


def _build_mock_fixture(
    template_slug: str,
    existing_fixtures: list[dict[str, Any]],
    *,
    label_override: str | None = None,
) -> dict[str, Any]:
    template = _FIXTURE_TEMPLATE_INDEX.get(template_slug)
    if template is None:
        raise KeyError(template_slug)

    same_type_count = sum(1 for fixture in existing_fixtures if fixture["type"] == template["type"])
    defaults = copy.deepcopy(template["defaults"])
    defaults["x"] = _clamp(float(defaults["x"]) + same_type_count * 0.07, 0.08, 0.92)
    defaults["address"] = int(defaults["address"]) + same_type_count * 20
    return {
        "id": f"{template_slug}-{uuid.uuid4().hex[:8]}",
        "templateSlug": template["slug"],
        "type": template["type"],
        "label": label_override or f"{template['label']} {same_type_count + 1}",
        **defaults,
        "phaseOffset": random.random() * math.pi * 2.0,
    }


def _scene_mix(scene: dict[str, Any], time_seconds: float) -> float:
    return 0.55 + math.sin(time_seconds * float(scene["speed_multiplier"]) * 2.0) * float(
        scene["pulse"]
    ) * 0.35


def _palette_pick(palette: list[str], phase: float, offset: float) -> str:
    """Choose a hex color from the scene palette that cycles with phase.

    Each fixture gets a different palette index driven by the scene
    rate, so the mock rig visibly sweeps through the scene's colors
    instead of holding whatever hex the fixture was created with.
    """
    if not palette:
        return "#ffffff"
    swept = (math.sin(phase * 0.45 + offset) + 1.0) * 0.5  # 0..1
    index = int(round(swept * (len(palette) - 1))) % len(palette)
    return palette[index]


def _fixture_output(
    fixture: dict[str, Any],
    scene: dict[str, Any],
    *,
    time_seconds: float,
    master_intensity: float,
    master_speed: float,
    blackout: bool,
) -> dict[str, Any]:
    mix = _scene_mix(scene, time_seconds)
    phase = time_seconds * master_speed * float(scene["speed_multiplier"]) + float(
        fixture["phaseOffset"]
    )
    base_intensity = float(fixture["intensity"]) * master_intensity * mix
    intensity = 0.0 if blackout else _clamp(base_intensity, 0.0, 1.0)
    # The fixture's "color" hex is a starting bias; during play we cycle
    # through the scene's palette. On blackout/black-out-intense fixtures
    # the caller has already zeroed intensity, so the hex doesn't matter.
    scene_palette = list(scene.get("palette") or [])
    if scene_palette:
        color = _palette_pick(scene_palette, phase, float(fixture["phaseOffset"]))
    else:
        color = _normalize_color(fixture["color"])
    red, green, blue = _hex_to_rgb(color)

    if fixture["type"] == "laser":
        return {
            "type": "laser",
            "color": color,
            "intensity": intensity,
            "channels": [
                ("Dim", round(intensity * 255)),
                ("Color", round(green)),
                ("Pattern", 160 + round((math.sin(phase) + 1.0) * 20)),
                ("Scan", round((0.2 + float(fixture["swing"]) * 0.8) * 255)),
            ],
        }

    if fixture["type"] == "moving_head":
        return {
            "type": "moving_head",
            "color": color,
            "intensity": intensity,
            "channels": [
                ("Dim", round(intensity * 255)),
                ("Pan", round(((math.sin(phase) * 0.5) + 0.5) * 255)),
                ("Tilt", round(((math.cos(phase * 0.8) * 0.5) + 0.5) * 255)),
                ("Color", round(red)),
            ],
        }

    if fixture["type"] == "wash":
        return {
            "type": "wash",
            "color": color,
            "intensity": intensity,
            "channels": [
                ("Dim", round(intensity * 255)),
                ("Red", red),
                ("Green", green),
                ("Blue", blue),
            ],
        }

    return {
        "type": "led_bar",
        "color": color,
        "intensity": intensity,
        "channels": [
            ("Dim", round(intensity * 255)),
            ("Pixels", _normalize_int(fixture["pixel_count"], 2, 16)),
            ("Chase", round(((math.sin(phase * 1.6) + 1.0) * 0.5) * 255)),
            ("Color", round(blue)),
        ],
    }


class MockRigStore:
    """Server-owned mock rig state for the browser preview."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._fixtures: list[dict[str, Any]] = []
        self._scene_id = MOCK_SCENE_TEMPLATES[0]["scene_id"]
        self._master_intensity = 0.82
        self._master_speed = 1.0
        self._blackout = False
        self._seed_default_rig()

    def _seed_default_rig(self) -> None:
        self._fixtures = []
        for entry in MOCK_DEFAULT_RIG:
            self._fixtures.append(
                _build_mock_fixture(entry["template"], self._fixtures, label_override=entry["label"])
            )

    def catalog(self) -> dict[str, Any]:
        return {
            "fixture_templates": copy.deepcopy(MOCK_FIXTURE_TEMPLATES),
            "scene_templates": copy.deepcopy(MOCK_SCENE_TEMPLATES),
            "default_rig": copy.deepcopy(MOCK_DEFAULT_RIG),
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "fixtures": copy.deepcopy(self._fixtures),
                "scene_id": self._scene_id,
                "master_intensity": self._master_intensity,
                "master_speed": self._master_speed,
                "blackout": self._blackout,
            }

    def _fixture_by_id(self, fixture_id: str) -> dict[str, Any] | None:
        for fixture in self._fixtures:
            if fixture["id"] == fixture_id:
                return fixture
        return None

    def create_fixture(self, template_slug: str, label: str | None = None) -> dict[str, Any]:
        with self._lock:
            fixture = _build_mock_fixture(template_slug, self._fixtures, label_override=label)
            self._fixtures.append(fixture)
            return copy.deepcopy(fixture)

    def duplicate_fixture(self, fixture_id: str) -> dict[str, Any] | None:
        with self._lock:
            fixture = self._fixture_by_id(fixture_id)
            if fixture is None:
                return None
            clone = copy.deepcopy(fixture)
            clone["id"] = f"{fixture['templateSlug']}-{uuid.uuid4().hex[:8]}"
            clone["label"] = f"{fixture['label']} Copy"
            clone["x"] = _clamp(float(fixture["x"]) + 0.05, 0.05, 0.95)
            clone["address"] = _normalize_int(int(fixture["address"]) + 10, 1, 512)
            self._fixtures.append(clone)
            return copy.deepcopy(clone)

    def delete_fixture(self, fixture_id: str) -> bool:
        with self._lock:
            original_len = len(self._fixtures)
            self._fixtures = [fixture for fixture in self._fixtures if fixture["id"] != fixture_id]
            return len(self._fixtures) != original_len

    def update_fixture(self, fixture_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            fixture = self._fixture_by_id(fixture_id)
            if fixture is None:
                return None

            for key, value in changes.items():
                if key == "label":
                    fixture["label"] = str(value).strip()[:80] or fixture["label"]
                elif key == "color":
                    fixture["color"] = _normalize_color(value)
                elif key == "intensity":
                    fixture["intensity"] = _normalize_float(value, 0.0, 1.0)
                elif key == "x":
                    fixture["x"] = _normalize_float(value, 0.05, 0.95)
                elif key == "y":
                    fixture["y"] = _normalize_float(value, 0.05, 0.60)
                elif key == "universe":
                    fixture["universe"] = _normalize_int(value, 1, 32)
                elif key == "address":
                    fixture["address"] = _normalize_int(value, 1, 512)
                elif key == "spread" and fixture["type"] == "laser":
                    fixture["spread"] = _normalize_float(value, 0.05, 0.55)
                elif key == "beam_count" and fixture["type"] == "laser":
                    fixture["beam_count"] = _normalize_int(value, 1, 9)
                elif key == "swing" and fixture["type"] == "laser":
                    fixture["swing"] = _normalize_float(value, 0.0, 1.0)
                elif key == "beam_width" and fixture["type"] == "moving_head":
                    fixture["beam_width"] = _normalize_float(value, 0.04, 0.25)
                elif key == "pan" and fixture["type"] == "moving_head":
                    fixture["pan"] = _normalize_float(value, -1.0, 1.0)
                elif key == "tilt" and fixture["type"] == "moving_head":
                    fixture["tilt"] = _normalize_float(value, 0.0, 1.0)
                elif key == "pan_range" and fixture["type"] == "moving_head":
                    fixture["pan_range"] = _normalize_float(value, 0.0, 1.0)
                elif key == "tilt_range" and fixture["type"] == "moving_head":
                    fixture["tilt_range"] = _normalize_float(value, 0.0, 1.0)
                elif key == "radius" and fixture["type"] == "wash":
                    fixture["radius"] = _normalize_float(value, 0.08, 0.40)
                elif key == "width" and fixture["type"] == "led_bar":
                    fixture["width"] = _normalize_float(value, 0.08, 0.35)
                elif key == "pixel_count" and fixture["type"] == "led_bar":
                    fixture["pixel_count"] = _normalize_int(value, 2, 16)

            return copy.deepcopy(fixture)

    def update_scene(self, scene_id: str) -> bool:
        if scene_id not in _SCENE_TEMPLATE_INDEX:
            return False
        with self._lock:
            self._scene_id = scene_id
        return True

    def update_masters(
        self,
        *,
        master_intensity: float | None = None,
        master_speed: float | None = None,
        blackout: bool | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if master_intensity is not None:
                self._master_intensity = _normalize_float(master_intensity, 0.0, 1.0)
            if master_speed is not None:
                self._master_speed = _normalize_float(master_speed, 0.2, 2.2)
            if blackout is not None:
                self._blackout = bool(blackout)
        return self.snapshot()

    def universe_snapshot(self, *, at_time: float | None = None) -> dict[str, Any]:
        state = self.snapshot()
        scene = _SCENE_TEMPLATE_INDEX[state["scene_id"]]
        generated_at = at_time if at_time is not None else time.time()
        universes: dict[int, dict[str, Any]] = {}

        for fixture in state["fixtures"]:
            output = _fixture_output(
                fixture,
                scene,
                time_seconds=generated_at,
                master_intensity=float(state["master_intensity"]),
                master_speed=float(state["master_speed"]),
                blackout=bool(state["blackout"]),
            )
            universe_id = int(fixture["universe"])
            universe = universes.setdefault(
                universe_id,
                {
                    "universe": universe_id,
                    "active_channel_count": 0,
                    "fixtures": [],
                    "channels": [],
                },
            )

            fixture_channels: list[dict[str, Any]] = []
            start_address = int(fixture["address"])
            for offset, (label, value) in enumerate(output["channels"]):
                channel = start_address + offset
                if channel > 512:
                    continue
                record = {
                    "channel": channel,
                    "offset": offset + 1,
                    "label": label,
                    "value": _normalize_int(value, 0, 255),
                }
                fixture_channels.append(record)
                universe["channels"].append(
                    {
                        "channel": channel,
                        "label": label,
                        "value": record["value"],
                        "fixture_id": fixture["id"],
                        "fixture_label": fixture["label"],
                    }
                )

            universe["fixtures"].append(
                {
                    "fixture_id": fixture["id"],
                    "fixture_label": fixture["label"],
                    "type": fixture["type"],
                    "address": fixture["address"],
                    "intensity": output["intensity"],
                    "channels": fixture_channels,
                }
            )

        ordered_universes = []
        for universe in sorted(universes.values(), key=lambda item: item["universe"]):
            universe["channels"].sort(key=lambda item: int(item["channel"]))
            universe["active_channel_count"] = len(universe["channels"])
            ordered_universes.append(universe)

        return {
            "generated_at": generated_at,
            "scene_id": state["scene_id"],
            "master_intensity": state["master_intensity"],
            "master_speed": state["master_speed"],
            "blackout": state["blackout"],
            "fixture_count": len(state["fixtures"]),
            "universes": ordered_universes,
        }


def _import_web_stack() -> tuple[Any, Any, Any, Any, Any, Any, Any]:
    try:
        from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
        from fastapi.responses import FileResponse, HTMLResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:  # pragma: no cover - exercised only in minimal envs
        raise RuntimeError(
            "The web control plane requires optional dependencies. "
            "Install with: pip install -e '.[web]'"
        ) from exc
    return (
        FastAPI,
        HTTPException,
        WebSocket,
        WebSocketDisconnect,
        HTMLResponse,
        FileResponse,
        StaticFiles,
    )


def _render_control_plane_html() -> str:
    return """
    <!DOCTYPE html>
    <html lang="en">
        <head>
            <meta charset="utf-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1" />
            <title>Photonic Synesthesia Control Plane</title>
            <link rel="stylesheet" href="/static/mock_control_plane.css" />
        </head>
        <body>
            <div id="app">
                <header class="hero">
                    <div>
                        <p class="eyebrow">Photonic Synesthesia</p>
                        <h1>Control Plane Mock Visualizer</h1>
                        <p class="lede">
                            Create fake lasers, movers, washes, and LED bars, then preview the scene in-browser before
                            touching real fixtures.
                        </p>
                    </div>
                    <div class="hero-metrics">
                        <div class="metric-card">
                            <span>WebSocket</span>
                            <strong id="ws-status">connecting</strong>
                        </div>
                        <div class="metric-card">
                            <span>Runtime Scene</span>
                            <strong id="runtime-scene">idle</strong>
                        </div>
                        <div class="metric-card">
                            <span>Fixture Count</span>
                            <strong id="fixture-count">0</strong>
                        </div>
                    </div>
                </header>

                <main class="layout">
                    <section class="panel stack" aria-label="Show controls">
                        <div class="panel-header">
                            <h2>Show Controls</h2>
                            <p>Mock rig controls inspired by lighting desks and virtual consoles.</p>
                        </div>

                        <div class="stack compact">
                            <label class="range-field">
                                <span>Master Intensity</span>
                                <input id="master-intensity" type="range" min="0" max="1" step="0.01" value="0.82" />
                                <strong id="master-intensity-value">82%</strong>
                            </label>
                            <label class="range-field">
                                <span>Master Speed</span>
                                <input id="master-speed" type="range" min="0.2" max="2.2" step="0.01" value="1.00" />
                                <strong id="master-speed-value">1.00x</strong>
                            </label>
                            <button id="blackout-toggle" class="panic">Blackout Off</button>
                        </div>

                        <div class="stack compact">
                            <div class="subhead">
                                <h3>Scene Bank</h3>
                                <p>Trigger fake looks locally while still observing live runtime telemetry.</p>
                            </div>
                            <div id="scene-bank" class="scene-bank"></div>
                        </div>

                        <div class="stack compact">
                            <div class="subhead">
                                <h3>Track Preview</h3>
                                <p>Hear the active file-backed session and watch a lightweight waveform preview.</p>
                            </div>
                            <div id="playback-panel" class="playback-panel empty">
                                Start a file-backed session with web mode to expose the current track here.
                            </div>
                        </div>

                        <div class="stack compact">
                            <div class="subhead">
                                <h3>Fixture Library</h3>
                                <p>Add simulated fixtures to the preview rig.</p>
                            </div>
                            <div id="fixture-library" class="fixture-library"></div>
                        </div>

                        <div class="stack compact">
                            <div class="subhead">
                                <h3>Rig</h3>
                                <p>Select a fixture to tune position, color, and behavior.</p>
                            </div>
                            <div id="fixture-list" class="fixture-list"></div>
                        </div>
                    </section>

                    <section class="panel preview-panel" aria-label="Stage preview">
                        <div class="panel-header wide">
                            <div>
                                <h2>Stage Preview</h2>
                                <p>Browser-only renderer with laser fans, beam cones, washes, and LED strip output.</p>
                            </div>
                            <div class="legend">
                                <span><i class="legend-chip laser"></i> Laser</span>
                                <span><i class="legend-chip mover"></i> Mover</span>
                                <span><i class="legend-chip wash"></i> Wash</span>
                                <span><i class="legend-chip bar"></i> LED Bar</span>
                            </div>
                        </div>
                        <canvas id="stage-canvas" width="1080" height="700"></canvas>
                        <div class="preview-footer">
                            <div>
                                <strong>Preview mode</strong>
                                <p>Local simulation only. No hardware output is sent from this screen.</p>
                            </div>
                            <div>
                                <strong>Live snapshot</strong>
                                <p id="runtime-summary">Waiting for control-plane state…</p>
                            </div>
                            <div>
                                <strong>Fixture Activity</strong>
                                <div id="fixture-activity" class="fixture-activity">
                                    Waiting for fixture output…
                                </div>
                            </div>
                        </div>
                    </section>

                    <section class="panel stack" aria-label="Inspector">
                        <div class="panel-header">
                            <h2>Fixture Inspector</h2>
                            <p>Per-fixture settings and a DMX-style monitor for the mock rig.</p>
                        </div>

                        <div id="fixture-inspector" class="inspector-empty">
                            Select a fixture to edit its mock parameters.
                        </div>

                        <div class="stack compact">
                            <div class="subhead">
                                <h3>Mock DMX Monitor</h3>
                                <p>Fixture-oriented synthetic channel output for the browser preview.</p>
                            </div>
                            <div id="dmx-monitor" class="dmx-monitor"></div>
                        </div>
                    </section>

                    <section class="panel stack show-editor-panel" aria-label="Agentic show editor">
                        <div class="panel-header wide">
                            <div>
                                <h2>Agentic Show</h2>
                                <p>Imported from Rekordbox and editable as a phrase timeline.</p>
                            </div>
                            <div class="editor-status">
                                <span>Track-coupled phrase timeline</span>
                            </div>
                        </div>

                        <div id="show-editor" class="show-editor">
                            <div class="show-editor-empty">Start a file-backed session with web mode to expose the current track timeline here.</div>
                        </div>
                    </section>
                </main>
            </div>

            <script src="/static/mock_control_plane.js"></script>
        </body>
    </html>
    """


def create_app(services: ControlPlaneStateService | None = None) -> Any:
    """Create the FastAPI control-plane application."""
    (
        FastAPI,
        HTTPException,
        WebSocket,
        WebSocketDisconnect,
        HTMLResponse,
        FileResponse,
        StaticFiles,
    ) = (
        _import_web_stack()
    )

    class ReleaseLeaseRequest(BaseModel):
        session_id: str
        force: bool = False

    class SessionEnvelope(BaseModel):
        issuer_id: str
        session_id: str
        role: OperatorRole = OperatorRole.OPERATOR

    class IntensityCommandRequest(SessionEnvelope):
        intensity: float

    class SpeedCommandRequest(SessionEnvelope):
        speed: float

    class SceneCommandRequest(SessionEnvelope):
        scene_id: str

    class MockFixtureCreateRequest(BaseModel):
        template_slug: str
        label: str | None = None

    class MockFixtureUpdateRequest(BaseModel):
        changes: dict[str, Any]

    class MockSceneStateRequest(BaseModel):
        scene_id: str

    class MockMasterStateRequest(BaseModel):
        master_intensity: float | None = None
        master_speed: float | None = None
        blackout: bool | None = None

    class PlaybackShowSectionUpdateRequest(BaseModel):
        changes: dict[str, Any]

    class PlaybackSeekRequest(BaseModel):
        seconds: float

    class PlaybackSelectionModeRequest(BaseModel):
        selection_mode: str

    class PlaybackSelectionVarianceRequest(BaseModel):
        selection_variance: float

    class PlaybackOperatorIntentRequest(BaseModel):
        intent: str
        scope: str = "track"
        target: str = "all"
        amount: float = 0.25
        expires_at: str | None = None

    class PlaybackProDJLinkTrackRequest(BaseModel):
        title: str
        artist: str | None = None
        duration_seconds: float | None = None
        expected_bpm: float | None = None
        playhead_seconds: float | None = None
        playing: bool | None = None
        finished: bool | None = None
        realtime: bool = True
        speed: float = 1.0
        selection_mode: str | None = None
        selection_variance: float | None = None

    app = FastAPI(
        title="Photonic Synesthesia Control Plane",
        version=__version__,
        summary="Control-plane service for live operation and future authoring flows.",
    )
    static_dir = Path(__file__).with_name("static")
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    services = services or get_shared_control_plane_service(create=True) or ControlPlaneStateService()
    app.state.services = services
    app.state.mock_rig = MockRigStore()
    app.state.playback_context = get_shared_playback_context()
    mock_rig: MockRigStore = app.state.mock_rig

    def require_control(session_id: str) -> None:
        if not services.has_control(session_id):
            raise HTTPException(status_code=403, detail="Active control lease required")

    def accept_command(command: OperatorCommand) -> dict[str, Any]:
        receipt = services.accept_command(command)
        return {
            "receipt": receipt.model_dump(mode="json"),
            "snapshot": services.snapshot().model_dump(mode="json"),
        }

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return _render_control_plane_html()

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/live/health")
    async def live_health() -> dict[str, Any]:
        return services.health(
            version=__version__,
            web_features=[
                "control_lease",
                "live_health",
                "live_snapshot",
                "live_safety",
                "mock_fixture_catalog",
                "mock_fixture_visualizer",
                "mock_rig_crud",
                "mock_universe_monitor",
                "websocket_live_feed",
            ],
        ).model_dump(mode="json")

    @app.get("/api/live/state")
    async def live_state() -> dict[str, Any]:
        services.publish_event(
            PlatformEventType.LIVE_STATE_PUBLISHED,
            "Live snapshot requested",
        )
        return services.snapshot().model_dump(mode="json")

    @app.get("/api/live/safety")
    async def live_safety() -> dict[str, Any]:
        snapshot = services.snapshot()
        return {
            "blackout_active": snapshot.blackout_active,
            "armed_live": snapshot.armed_live,
            "safety_summary": snapshot.safety_summary.model_dump(mode="json"),
            "active_control_lease": snapshot.active_control_lease.model_dump(mode="json")
            if snapshot.active_control_lease
            else None,
            "recent_events": [event.model_dump(mode="json") for event in snapshot.recent_events],
        }

    @app.get("/api/mock/catalog")
    async def mock_catalog() -> dict[str, Any]:
        return mock_rig.catalog()

    @app.get("/api/mock/state")
    async def mock_state() -> dict[str, Any]:
        return mock_rig.snapshot()

    @app.get("/api/mock/universes")
    async def mock_universes() -> dict[str, Any]:
        return mock_rig.universe_snapshot()

    @app.get("/api/mock/playback")
    async def mock_playback() -> dict[str, Any]:
        playback_context: PlaybackContext | None = get_shared_playback_context()
        if playback_context is None:
            return {"available": False}
        return playback_context.snapshot()

    @app.get("/api/mock/playback/audio")
    async def mock_playback_audio(session: str | None = None) -> Any:
        playback_context: PlaybackContext | None = get_shared_playback_context()
        if playback_context is None:
            raise HTTPException(status_code=404, detail="No playback file is active")
        if session is not None and session != playback_context.session_id:
            raise HTTPException(status_code=404, detail="Playback session is no longer active")
        media_path = Path(playback_context.file_path)
        if not media_path.is_file():
            raise HTTPException(status_code=404, detail="Playback file is missing")
        media_type = "audio/mpeg" if media_path.suffix.lower() == ".mp3" else None
        return FileResponse(
            media_path,
            media_type=media_type,
            headers={"Accept-Ranges": "bytes"},
        )

    @app.get("/api/mock/playback/ilda-export")
    async def mock_playback_ilda_export(session: str | None = None) -> Any:
        playback_context: PlaybackContext | None = get_shared_playback_context()
        if playback_context is None:
            raise HTTPException(status_code=404, detail="No playback file is active")
        if session is not None and session != playback_context.session_id:
            raise HTTPException(status_code=404, detail="Playback session is no longer active")
        export_path = Path(playback_context.ilda_export_path)
        if not playback_context.ilda_export_path or not export_path.is_file():
            raise HTTPException(status_code=404, detail="No ILDA export is available")
        media_type = "application/octet-stream"
        filename = export_path.name
        return FileResponse(export_path, media_type=media_type, filename=filename)

    @app.patch("/api/mock/playback/show-sections/{section_id}")
    async def update_playback_show_section(
        section_id: str, request: PlaybackShowSectionUpdateRequest
    ) -> dict[str, Any]:
        playback_context: PlaybackContext | None = get_shared_playback_context()
        if playback_context is None:
            raise HTTPException(status_code=404, detail="No playback file is active")
        section = playback_context.update_show_section(section_id, request.changes)
        if section is None:
            raise HTTPException(status_code=404, detail="Show section not found")
        return playback_context.snapshot()

    @app.patch("/api/mock/playback/selection-mode")
    async def update_playback_selection_mode(
        request: PlaybackSelectionModeRequest,
    ) -> dict[str, Any]:
        playback_context: PlaybackContext | None = get_shared_playback_context()
        if playback_context is None:
            raise HTTPException(status_code=404, detail="No playback file is active")
        try:
            return playback_context.set_selection_mode(request.selection_mode)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.patch("/api/mock/playback/selection-variance")
    async def update_playback_selection_variance(
        request: PlaybackSelectionVarianceRequest,
    ) -> dict[str, Any]:
        playback_context: PlaybackContext | None = get_shared_playback_context()
        if playback_context is None:
            raise HTTPException(status_code=404, detail="No playback file is active")
        try:
            return playback_context.set_selection_variance(request.selection_variance)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/mock/playback/operator-intents")
    async def apply_playback_operator_intent(
        request: PlaybackOperatorIntentRequest,
    ) -> dict[str, Any]:
        playback_context: PlaybackContext | None = get_shared_playback_context()
        if playback_context is None:
            raise HTTPException(status_code=404, detail="No playback file is active")
        try:
            return playback_context.apply_operator_intent(
                intent=request.intent,
                scope=request.scope,
                target=request.target,
                amount=request.amount,
                expires_at=request.expires_at or "",
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/mock/playback/pro-dj-link/track")
    async def bind_playback_pro_dj_link_track(
        request: PlaybackProDJLinkTrackRequest,
    ) -> dict[str, Any]:
        playback_context: PlaybackContext | None = get_shared_playback_context()
        if playback_context is None:
            raise HTTPException(status_code=404, detail="No playback session is active")
        try:
            return playback_context.bind_track_metadata(
                {
                    "track_title": request.title,
                    "track_artist": request.artist or "",
                    "duration_seconds": request.duration_seconds,
                    "expected_bpm": request.expected_bpm,
                    "playhead_seconds": request.playhead_seconds,
                    "playing": request.playing,
                    "finished": request.finished,
                    "realtime": request.realtime,
                    "speed": request.speed,
                    "selection_mode": request.selection_mode,
                    "selection_variance": request.selection_variance,
                    "metadata_source": "pro_dj_link",
                }
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/mock/playback/seek")
    async def seek_playback(request: PlaybackSeekRequest) -> dict[str, Any]:
        playback_context: PlaybackContext | None = get_shared_playback_context()
        if playback_context is None:
            raise HTTPException(status_code=404, detail="No playback file is active")
        try:
            playback_context.request_seek(request.seconds)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return playback_context.snapshot()

    @app.post("/api/mock/fixtures")
    async def create_mock_fixture(request: MockFixtureCreateRequest) -> dict[str, Any]:
        if request.template_slug not in _FIXTURE_TEMPLATE_INDEX:
            raise HTTPException(status_code=404, detail="Unknown fixture template")
        fixture = mock_rig.create_fixture(request.template_slug, request.label)
        return {"fixture": fixture, "state": mock_rig.snapshot()}

    @app.patch("/api/mock/fixtures/{fixture_id}")
    async def update_mock_fixture(
        fixture_id: str, request: MockFixtureUpdateRequest
    ) -> dict[str, Any]:
        fixture = mock_rig.update_fixture(fixture_id, request.changes)
        if fixture is None:
            raise HTTPException(status_code=404, detail="Fixture not found")
        return {"fixture": fixture, "state": mock_rig.snapshot()}

    @app.post("/api/mock/fixtures/{fixture_id}/duplicate")
    async def duplicate_mock_fixture(fixture_id: str) -> dict[str, Any]:
        fixture = mock_rig.duplicate_fixture(fixture_id)
        if fixture is None:
            raise HTTPException(status_code=404, detail="Fixture not found")
        return {"fixture": fixture, "state": mock_rig.snapshot()}

    @app.delete("/api/mock/fixtures/{fixture_id}")
    async def delete_mock_fixture(fixture_id: str) -> dict[str, Any]:
        if not mock_rig.delete_fixture(fixture_id):
            raise HTTPException(status_code=404, detail="Fixture not found")
        return {"deleted": True, "state": mock_rig.snapshot()}

    @app.post("/api/mock/scene")
    async def update_mock_scene(request: MockSceneStateRequest) -> dict[str, Any]:
        if not mock_rig.update_scene(request.scene_id):
            raise HTTPException(status_code=404, detail="Unknown mock scene")
        return mock_rig.snapshot()

    @app.post("/api/mock/masters")
    async def update_mock_masters(request: MockMasterStateRequest) -> dict[str, Any]:
        return mock_rig.update_masters(
            master_intensity=request.master_intensity,
            master_speed=request.master_speed,
            blackout=request.blackout,
        )

    @app.post("/api/control/lease/acquire")
    async def acquire_control_lease(request: LeaseAcquireRequest) -> dict[str, Any]:
        response = services.acquire_control_lease(request)
        return response.model_dump(mode="json")

    @app.post("/api/control/lease/release")
    async def release_control_lease(request: ReleaseLeaseRequest) -> dict[str, Any]:
        released = services.release_control_lease(request.session_id, force=request.force)
        if not released:
            raise HTTPException(status_code=404, detail="No matching control lease to release")
        return {
            "released": True,
            "active_control_lease": None,
        }

    @app.post("/api/control/arm")
    async def arm_live(request: SessionEnvelope) -> dict[str, Any]:
        require_control(request.session_id)
        return accept_command(
            OperatorCommand(
                issuer_id=request.issuer_id,
                session_id=request.session_id,
                role=request.role,
                command_type=CommandType.ARM,
            )
        )

    @app.post("/api/control/disarm")
    async def disarm_live(request: SessionEnvelope) -> dict[str, Any]:
        require_control(request.session_id)
        return accept_command(
            OperatorCommand(
                issuer_id=request.issuer_id,
                session_id=request.session_id,
                role=request.role,
                command_type=CommandType.DISARM,
            )
        )

    @app.post("/api/control/blackout")
    async def activate_blackout(request: SessionEnvelope) -> dict[str, Any]:
        require_control(request.session_id)
        return accept_command(
            OperatorCommand(
                issuer_id=request.issuer_id,
                session_id=request.session_id,
                role=request.role,
                command_type=CommandType.BLACKOUT,
            )
        )

    @app.post("/api/control/clear-blackout")
    async def clear_blackout(request: SessionEnvelope) -> dict[str, Any]:
        require_control(request.session_id)
        return accept_command(
            OperatorCommand(
                issuer_id=request.issuer_id,
                session_id=request.session_id,
                role=request.role,
                command_type=CommandType.CLEAR_BLACKOUT,
            )
        )

    @app.post("/api/control/intensity")
    async def set_intensity(request: IntensityCommandRequest) -> dict[str, Any]:
        require_control(request.session_id)
        return accept_command(
            OperatorCommand(
                issuer_id=request.issuer_id,
                session_id=request.session_id,
                role=request.role,
                command_type=CommandType.SET_GLOBAL_INTENSITY,
                payload={"intensity": request.intensity},
            )
        )

    @app.post("/api/control/speed")
    async def set_speed(request: SpeedCommandRequest) -> dict[str, Any]:
        require_control(request.session_id)
        return accept_command(
            OperatorCommand(
                issuer_id=request.issuer_id,
                session_id=request.session_id,
                role=request.role,
                command_type=CommandType.SET_GLOBAL_SPEED,
                payload={"speed": request.speed},
            )
        )

    @app.post("/api/control/scenes/launch")
    async def launch_scene(request: SceneCommandRequest) -> dict[str, Any]:
        require_control(request.session_id)
        return accept_command(
            OperatorCommand(
                issuer_id=request.issuer_id,
                session_id=request.session_id,
                role=request.role,
                command_type=CommandType.LAUNCH_SCENE,
                payload={"scene_id": request.scene_id},
            )
        )

    @app.post("/api/control/scenes/hold")
    async def hold_scene(request: SceneCommandRequest) -> dict[str, Any]:
        require_control(request.session_id)
        return accept_command(
            OperatorCommand(
                issuer_id=request.issuer_id,
                session_id=request.session_id,
                role=request.role,
                command_type=CommandType.HOLD_SCENE,
                payload={"scene_id": request.scene_id},
            )
        )

    @app.post("/api/control/scenes/release-hold")
    async def release_scene_hold(request: SessionEnvelope) -> dict[str, Any]:
        require_control(request.session_id)
        return accept_command(
            OperatorCommand(
                issuer_id=request.issuer_id,
                session_id=request.session_id,
                role=request.role,
                command_type=CommandType.RELEASE_SCENE_HOLD,
            )
        )

    @app.websocket("/ws/live")
    async def websocket_live(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            while True:
                await websocket.send_json(services.snapshot().model_dump(mode="json"))
                await asyncio.sleep(1.0)
        except WebSocketDisconnect:
            return

    return app


def main() -> None:
    """Run the control-plane service."""
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - exercised only in minimal envs
        sys.stderr.write("uvicorn is required for `photonic-web`. Install with `pip install -e '.[web]'`.\n")
        raise SystemExit(1) from exc

    app = create_app()
    host = os.getenv("PHOTONIC_WEB_HOST", "127.0.0.1")
    port = int(os.getenv("PHOTONIC_WEB_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)


def serve_in_thread(
    *,
    services: ControlPlaneStateService | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> tuple[Any, threading.Thread]:
    """Start the control-plane app in a background thread."""
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - exercised only in minimal envs
        raise RuntimeError(
            "uvicorn is required for embedded web serving. Install with: pip install -e '.[web]'"
        ) from exc

    app = create_app(services=services)
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="photonic-web", daemon=True)
    thread.start()

    deadline = time.time() + 5.0
    while not server.started:
        if not thread.is_alive():
            raise RuntimeError("Embedded web server terminated before startup completed")
        if time.time() >= deadline:
            raise RuntimeError("Timed out waiting for embedded web server startup")
        time.sleep(0.05)

    # Ensure the port is actually accepting connections before returning.
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            if sock.connect_ex((host, port)) == 0:
                break
        time.sleep(0.05)

    return server, thread
