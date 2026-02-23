#!/usr/bin/env python3
"""
Dashboard frontend/backend endpoint parity checker.

Goal: prevent silent breakage where the dashboard JS calls `/api/*` routes that
aren't implemented (or changed) in the FastAPI server.

This is intentionally lightweight and repo-specific:
- Frontend: ai_orchestrator/dashboard/static/js/app.js
- Backend:  ai_orchestrator/dashboard/server.py

Exit codes:
- 0: parity OK
- 1: parity FAIL (missing backend routes for some frontend endpoints)
- 2: error (unexpected failure)
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BackendRoute:
    method: str
    path: str
    lineno: int


_BACKEND_DECORATOR_RE = re.compile(
    r"^@app\.(get|post|put|delete|patch|websocket)\(\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)


def _extract_backend_routes(backend_file: Path) -> list[BackendRoute]:
    routes: list[BackendRoute] = []
    for lineno, line in enumerate(backend_file.read_text(encoding="utf-8").splitlines(), 1):
        m = _BACKEND_DECORATOR_RE.match(line.strip())
        if not m:
            continue
        method, path = m.group(1).upper(), m.group(2)
        routes.append(BackendRoute(method=method, path=path, lineno=lineno))
    return routes


def _normalize_frontend_path(raw: str) -> str:
    # Drop query string
    raw = raw.split("?", 1)[0]
    # Normalize dynamic template `${x}` into `{param}` so it matches FastAPI path params.
    raw = re.sub(r"\$\{[^}]+\}", "{param}", raw)
    return raw


def _extract_frontend_paths(frontend_file: Path) -> set[str]:
    text = frontend_file.read_text(encoding="utf-8")

    paths: set[str] = set()

    # fetch('/api/...') and fetch("/api/...")
    for m in re.finditer(r"fetch\(\s*['\"](/[^'\"]+)['\"]", text):
        paths.add(_normalize_frontend_path(m.group(1)))

    # fetch(`/api/...${x}...`)
    for m in re.finditer(r"fetch\(\s*`(/[^`]+)`", text):
        paths.add(_normalize_frontend_path(m.group(1)))

    # WebSocket URL construction: `${protocol}//${window.location.host}/ws`
    # We consider `/ws` part of parity.
    if re.search(r"/ws\b", text):
        paths.add("/ws")

    # Only dashboard API (and ws) are in-scope.
    return {p for p in paths if p.startswith("/api/") or p == "/ws"}


def _path_matches(pattern: str, concrete: str) -> bool:
    """
    Compare two paths where either side can contain FastAPI-style `{param}` segments.
    """
    p_segs = [s for s in pattern.strip("/").split("/") if s]
    c_segs = [s for s in concrete.strip("/").split("/") if s]
    if len(p_segs) != len(c_segs):
        return False
    for p, c in zip(p_segs, c_segs, strict=True):
        if p.startswith("{") and p.endswith("}"):
            continue
        if c.startswith("{") and c.endswith("}"):
            continue
        if p != c:
            return False
    return True


def run(frontend_file: Path, backend_file: Path) -> int:
    if not frontend_file.exists():
        print(f"[ERROR] Frontend file not found: {frontend_file}")
        return 2
    if not backend_file.exists():
        print(f"[ERROR] Backend file not found: {backend_file}")
        return 2

    frontend_paths = sorted(_extract_frontend_paths(frontend_file))
    backend_routes = _extract_backend_routes(backend_file)

    backend_paths = {r.path for r in backend_routes}
    missing: list[str] = []

    for fp in frontend_paths:
        if any(_path_matches(fp, bp) for bp in backend_paths):
            continue
        missing.append(fp)

    print("Dashboard Endpoint Parity Check")
    print(f"Frontend: {frontend_file}")
    print(f"Backend:  {backend_file}")
    print()
    print(f"Frontend endpoints: {len(frontend_paths)}")
    for p in frontend_paths:
        print(f"  - {p}")
    print()
    print(f"Backend routes: {len(backend_routes)}")
    for r in backend_routes:
        print(f"  - {r.method} {r.path} ({backend_file}:{r.lineno})")
    print()

    if missing:
        print("FAIL: Missing backend routes for frontend endpoints:")
        for p in missing:
            print(f"  - {p}")
        return 1

    print("PASS: All frontend endpoints have backend route matches.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check dashboard frontend/backend endpoint parity."
    )
    parser.add_argument(
        "--frontend",
        type=Path,
        default=Path("ai_orchestrator/dashboard/static/js/app.js"),
        help="Path to dashboard frontend JS (default: ai_orchestrator/dashboard/static/js/app.js)",
    )
    parser.add_argument(
        "--backend",
        type=Path,
        default=Path("ai_orchestrator/dashboard/server.py"),
        help="Path to FastAPI server file (default: ai_orchestrator/dashboard/server.py)",
    )
    args = parser.parse_args()
    try:
        return run(args.frontend, args.backend)
    except Exception as exc:  # pragma: no cover
        print(f"[ERROR] Unexpected failure: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
