"""FastAPI-based control plane for the optional web interface."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

from photonic_synesthesia import __version__
from photonic_synesthesia.platform import (
    CommandType,
    ControlPlaneStateService,
    LeaseAcquireRequest,
    OperatorCommand,
    OperatorRole,
    PlatformEventType,
    get_shared_control_plane_service,
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


def _import_web_stack() -> tuple[Any, Any, Any, Any, Any, Any, Any]:
    try:
        from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
        from fastapi.responses import HTMLResponse
        from fastapi.staticfiles import StaticFiles
        from pydantic import BaseModel
    except ImportError as exc:  # pragma: no cover - exercised only in minimal envs
        raise RuntimeError(
            "The web control plane requires optional dependencies. "
            "Install with: pip install -e '.[web]'"
        ) from exc
    return FastAPI, HTTPException, WebSocket, WebSocketDisconnect, HTMLResponse, StaticFiles, BaseModel


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
                </main>
            </div>

            <script src="/static/mock_control_plane.js"></script>
        </body>
    </html>
    """


def create_app(services: ControlPlaneStateService | None = None) -> Any:
    """Create the FastAPI control-plane application."""
    FastAPI, HTTPException, WebSocket, WebSocketDisconnect, HTMLResponse, StaticFiles, BaseModel = (
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
        return {
            "fixture_templates": MOCK_FIXTURE_TEMPLATES,
            "scene_templates": MOCK_SCENE_TEMPLATES,
            "default_rig": MOCK_DEFAULT_RIG,
        }

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
    async def websocket_live(websocket: Any) -> None:
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
