"""FastAPI-based control plane for the optional web interface."""

from __future__ import annotations

import asyncio
import os
import sys
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


def _import_web_stack() -> tuple[Any, Any, Any, Any, Any, Any]:
    try:
        from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
        from fastapi.responses import HTMLResponse
        from pydantic import BaseModel
    except ImportError as exc:  # pragma: no cover - exercised only in minimal envs
        raise RuntimeError(
            "The web control plane requires optional dependencies. "
            "Install with: pip install -e '.[web]'"
        ) from exc
    return FastAPI, HTTPException, WebSocket, WebSocketDisconnect, HTMLResponse, BaseModel


def create_app(services: ControlPlaneStateService | None = None) -> Any:
    """Create the FastAPI control-plane application."""
    FastAPI, HTTPException, WebSocket, WebSocketDisconnect, HTMLResponse, BaseModel = (
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
        return """
        <html>
            <head><title>Photonic Synesthesia Control Plane</title></head>
            <body>
                <h1>Photonic Synesthesia Control Plane</h1>
                <p>The FastAPI control-plane service is running.</p>
                <ul>
                    <li><code>GET /api/live/health</code></li>
                    <li><code>GET /api/live/state</code></li>
                    <li><code>POST /api/control/lease/acquire</code></li>
                    <li><code>POST /api/control/lease/release</code></li>
                    <li><code>POST /api/control/blackout</code></li>
                    <li><code>POST /api/control/intensity</code></li>
                    <li><code>WS /ws/live</code></li>
                </ul>
            </body>
        </html>
        """

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
