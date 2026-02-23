#!/usr/bin/env python3
"""
Route Parity Check (Plan -> FastAPI Decorators -> Mounts/Fallback Scan)

Goal: Prevent "sounds-right" webhook/API paths that do not exist in code.

This script is intentionally conservative and deterministic:
- It does not import the FastAPI app (avoids env-dependent import failures).
- It parses route decorators + router prefixes from source files.
- If a `backend/` layout is present, it parses include_router mounts from `backend/main.py`
  and composes final paths from `backend/api/**/*.py`.
- Otherwise, it falls back to scanning `@app.<method>("/path")` decorators repo-wide.
- It validates that each plan-claimed route path matches at least one known route.

Exit codes:
  0 = all claimed routes matched
  1 = one or more claimed routes did not match
  2 = script error / invalid args
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT_DEFAULT = Path(__file__).resolve().parents[2]
BACKEND_API_DIR = Path("backend") / "api"
BACKEND_MAIN = Path("backend") / "main.py"


@dataclass(frozen=True)
class RouteClaim:
    path: str
    line: int
    source: str  # e.g. "backticks", "METHOD PATH", "bare"
    line_text: str


@dataclass(frozen=True)
class RouteDef:
    method: str
    path: str  # decorated path joined with router prefix (not include_router mount)
    file: str
    line: int
    router_prefix: str


@dataclass
class RouteIndex:
    # module_key -> include_router prefixes (may have multiple)
    mounts: dict[str, list[str]]
    # module_key -> route defs in that module
    routes_by_module: dict[str, list[RouteDef]]
    # all composed final paths (include_router prefix + module route path)
    final_paths: set[str]
    # compiled matchers to support {param} placeholders
    final_path_regexes: list[tuple[str, re.Pattern[str]]]


def _norm_path(p: str) -> str:
    p = (p or "").strip()
    if not p.startswith("/"):
        p = "/" + p
    # collapse double slashes
    p = re.sub(r"/{2,}", "/", p)
    # remove trailing slash except root
    if p != "/" and p.endswith("/"):
        p = p[:-1]
    return p


def _join(prefix: str, path: str) -> str:
    if not prefix:
        return _norm_path(path)
    return _norm_path(prefix.rstrip("/") + "/" + path.lstrip("/"))


def _route_to_regex(path: str) -> re.Pattern[str]:
    # Convert "/foo/{id}/bar" to a matcher that accepts any non-slash segment for params.
    escaped = re.escape(path)
    escaped = re.sub(r"\\\{[^\\\}]+\\\}", r"[^/]+", escaped)
    return re.compile(rf"^{escaped}$")


def _iter_non_code_lines(text: str) -> list[tuple[int, str]]:
    lines = text.splitlines()
    in_fence = False
    out: list[tuple[int, str]] = []
    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        out.append((idx, line))
    return out


def extract_route_claims(plan_text: str) -> list[RouteClaim]:
    claims: list[RouteClaim] = []
    seen: set[tuple[str, int]] = set()

    # 1) Backticked paths like `/api/webhooks/whatsapp`
    backtick = re.compile(r"`(/[^`\s]+)`")
    # 2) METHOD /path patterns
    method_path = re.compile(r"\b(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s+(/[^`\s]+)")
    # 3) Bare paths (NOT inside code fences). Intentionally strict:
    # - must start at start-of-line or after non-path char (prevents matching "backend/api/foo.py")
    # - must not be immediately preceded by "/" (prevents matching within "https://")
    # - must be a plausible route with at least one segment after the namespace
    bare = re.compile(
        r"(?<![A-Za-z0-9_.-])(?<!/)"
        r"(?P<path>/(?:api|webhooks|position-statements|cases|client-documents)"
        r"(?:/[A-Za-z0-9_~{}:-]+)+)"
    )

    def _strip_trailing_punct(p: str) -> str:
        return p.rstrip(").,;:")

    def _looks_like_file(p: str) -> bool:
        return bool(re.search(r"\.(py|ts|tsx|md|json|yml|yaml|txt)$", p, re.IGNORECASE))

    for line_no, line in _iter_non_code_lines(plan_text):
        for m in backtick.finditer(line):
            path = _strip_trailing_punct(_norm_path(m.group(1)))
            if _looks_like_file(path):
                continue
            key = (path, line_no)
            if key not in seen:
                claims.append(
                    RouteClaim(path=path, line=line_no, source="backticks", line_text=line.rstrip())
                )
                seen.add(key)
        for m in method_path.finditer(line):
            path = _strip_trailing_punct(_norm_path(m.group(2)))
            if _looks_like_file(path):
                continue
            key = (path, line_no)
            if key not in seen:
                claims.append(
                    RouteClaim(
                        path=path,
                        line=line_no,
                        source=f"{m.group(1)} PATH",
                        line_text=line.rstrip(),
                    )
                )
                seen.add(key)
        for m in bare.finditer(line):
            path = _strip_trailing_punct(_norm_path(m.group("path")))
            if _looks_like_file(path):
                continue
            key = (path, line_no)
            if key not in seen:
                claims.append(
                    RouteClaim(path=path, line=line_no, source="bare", line_text=line.rstrip())
                )
                seen.add(key)

    return claims


def _extract_router_prefix(content: str) -> str:
    # router = APIRouter(prefix="/api/foo", ...)
    # NOTE: keep simple + deterministic (no AST).
    m = re.search(r"APIRouter\s*\(\s*[^)]*?\bprefix\s*=\s*['\"]([^'\"]+)['\"]", content, re.DOTALL)
    if not m:
        return ""
    return _norm_path(m.group(1))


def _extract_route_decorators(content: str) -> list[tuple[str, str, int]]:
    # Matches @router.get("/path") even if the string literal is on the next line.
    # We keep only the first string literal argument.
    deco = re.compile(
        r"@\s*router\.(get|post|put|delete|patch|options|head|websocket)\s*\(\s*['\"]([^'\"]+)['\"]",
        re.IGNORECASE | re.MULTILINE,
    )
    out: list[tuple[str, str, int]] = []
    for m in deco.finditer(content):
        method = m.group(1).lower()
        path = m.group(2)
        line = content[: m.start()].count("\n") + 1
        out.append((method, _norm_path(path), line))
    return out


def _module_key_for_api_file(api_file: Path, api_root: Path) -> str:
    # backend/api/foo_bar.py -> foo_bar
    # backend/api/sub/mod.py -> sub.mod (best-effort)
    rel = api_file.relative_to(api_root)
    return ".".join(rel.with_suffix("").parts)


def _parse_include_router_mounts(main_py: str) -> dict[str, list[str]]:
    mounts: dict[str, list[str]] = {}
    # app.include_router(messaging_webhooks.router, prefix="/api", ...)
    inc = re.compile(
        r"include_router\s*\(\s*([A-Za-z0-9_\.]+)\s*,\s*(?:[^)]*?\bprefix\s*=\s*['\"]([^'\"]+)['\"])?",
        re.DOTALL,
    )
    for m in inc.finditer(main_py):
        router_expr = m.group(1)
        prefix = m.group(2) or ""
        prefix = _norm_path(prefix) if prefix else ""

        # Derive a best-effort key. Usually "<module>.router" where module is imported in backend/main.py.
        parts = router_expr.split(".")
        if parts and parts[-1] == "router" and len(parts) >= 2:
            key = ".".join(parts[:-1])
        else:
            key = router_expr

        mounts.setdefault(key, [])
        if prefix not in mounts[key]:
            mounts[key].append(prefix)
    return mounts


def _extract_app_route_decorators(content: str) -> list[tuple[str, str, int]]:
    """
    Extract @app.<method>("/path") decorators with line numbers.

    This supports repos that mount routes directly on the FastAPI app (common for dashboards)
    and repos without a `backend/` layout.
    """
    decorators: list[tuple[str, str, int]] = []
    deco = re.compile(
        r"@\s*app\.(get|post|put|delete|patch|options|head|websocket)\s*\(\s*['\"]([^'\"]+)['\"]",
        re.IGNORECASE,
    )
    for i, line in enumerate(content.splitlines(), start=1):
        m = deco.search(line)
        if not m:
            continue
        decorators.append((m.group(1).upper(), m.group(2), i))
    return decorators


def _build_route_index_backend_layout(project_root: Path) -> RouteIndex:
    api_root = (project_root / BACKEND_API_DIR).resolve()
    main_path = (project_root / BACKEND_MAIN).resolve()

    if not api_root.exists():
        raise FileNotFoundError(f"backend api dir not found: {api_root}")
    if not main_path.exists():
        raise FileNotFoundError(f"backend main.py not found: {main_path}")

    main_text = main_path.read_text(encoding="utf-8", errors="replace")
    mounts = _parse_include_router_mounts(main_text)

    routes_by_module: dict[str, list[RouteDef]] = {}

    for py in sorted(api_root.rglob("*.py")):
        if py.name.startswith("_"):
            continue
        try:
            content = py.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        module_key = _module_key_for_api_file(py, api_root)
        router_prefix = _extract_router_prefix(content)
        decorators = _extract_route_decorators(content)
        if not decorators:
            continue
        for method, path, line in decorators:
            joined = _join(router_prefix, path)
            routes_by_module.setdefault(module_key, []).append(
                RouteDef(
                    method=method,
                    path=joined,
                    file=str(py.relative_to(project_root)),
                    line=line,
                    router_prefix=router_prefix,
                )
            )

    # In main.py it's common to import modules under a local alias (e.g. "from api.tools import adr_calculator"),
    # and then include_router(adr_calculator.router). To support this without over-claiming, we allow a
    # last-segment mount key fallback ONLY when the last segment is unique across backend/api modules.
    last_seg_to_modules: dict[str, set[str]] = {}
    for mk in routes_by_module:
        last_seg_to_modules.setdefault(mk.split(".")[-1], set()).add(mk)

    final_paths: set[str] = set()
    for module_key, defs in routes_by_module.items():
        candidate_mount_keys = {module_key}
        last_seg = module_key.split(".")[-1]
        if len(last_seg_to_modules.get(last_seg, set())) == 1:
            candidate_mount_keys.add(last_seg)
        prefixes: list[str] = []
        for k in candidate_mount_keys:
            prefixes.extend(mounts.get(k, []))
        # Package mount support:
        # If backend/main.py mounts "mediation.router" but the decorators live in "mediation.routes",
        # apply the mount prefix to any module under that package.
        if not prefixes:
            for mount_key, mount_prefixes in mounts.items():
                if module_key.startswith(mount_key + "."):
                    prefixes.extend(mount_prefixes)
        # Fail closed: if we can't prove this router is mounted (directly or via package mount),
        # don't treat its decorators as live routes.
        if not prefixes:
            continue
        for d in defs:
            for pref in prefixes:
                final_paths.add(_join(pref, d.path))

    final_path_regexes: list[tuple[str, re.Pattern[str]]] = []
    for p in sorted(final_paths):
        final_path_regexes.append((p, _route_to_regex(p)))

    return RouteIndex(
        mounts=mounts,
        routes_by_module=routes_by_module,
        final_paths=final_paths,
        final_path_regexes=final_path_regexes,
    )


def _build_route_index_fallback(project_root: Path) -> RouteIndex:
    """
    Fallback mode for repos without a `backend/` layout.

    We intentionally restrict this to `@app.<method>` decorators because those are already
    fully composed paths. Routers mounted via `include_router` are difficult to compose
    deterministically without importing the app; those repos should prefer the backend-layout mode.
    """
    final_paths: set[str] = set()
    routes_by_module: dict[str, list[RouteDef]] = {}

    for py in sorted(project_root.rglob("*.py")):
        parts = set(py.parts)
        if "__pycache__" in parts or ".venv" in parts or "venv" in parts:
            continue
        if py.name.startswith("."):
            continue
        try:
            content = py.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        for method, path, line in _extract_app_route_decorators(content):
            norm = _norm_path(path)
            final_paths.add(norm)
            routes_by_module.setdefault(str(py.relative_to(project_root)), []).append(
                RouteDef(
                    method=method,
                    path=norm,
                    file=str(py.relative_to(project_root)),
                    line=line,
                    router_prefix="",
                )
            )

    final_path_regexes: list[tuple[str, re.Pattern[str]]] = []
    for p in sorted(final_paths):
        final_path_regexes.append((p, _route_to_regex(p)))

    return RouteIndex(
        mounts={},
        routes_by_module=routes_by_module,
        final_paths=final_paths,
        final_path_regexes=final_path_regexes,
    )


def build_route_index(project_root: Path) -> RouteIndex:
    api_root = (project_root / BACKEND_API_DIR).resolve()
    main_path = (project_root / BACKEND_MAIN).resolve()
    if api_root.exists() and main_path.exists():
        return _build_route_index_backend_layout(project_root)
    return _build_route_index_fallback(project_root)


def match_claim(claim_path: str, idx: RouteIndex) -> str | None:
    claim_path = _norm_path(claim_path)
    if claim_path in idx.final_paths:
        return claim_path
    # Accept explicit wildcard claims like "/api/foo/*" as "any concrete route below this prefix".
    if claim_path.endswith("/*"):
        base = claim_path[:-2].rstrip("/")
        prefix = base + "/"
        for p in idx.final_paths:
            if p == base or p.startswith(prefix):
                return p
        return None
    # Accept router-prefix claims like "/api/strategy-tribunal" if any concrete route exists under it.
    prefix = claim_path.rstrip("/") + "/"
    for p in idx.final_paths:
        if p.startswith(prefix):
            return claim_path
    # Accept uniquely-identifying suffix claims where mount prefix is omitted,
    # e.g. "/results/{analysis_id}" matching "/api/strategy-tribunal/results/{analysis_id}".
    suffix_matches = [p for p in idx.final_paths if p.endswith(claim_path)]
    if len(suffix_matches) == 1:
        return suffix_matches[0]
    for route_path, rx in idx.final_path_regexes:
        if rx.match(claim_path):
            return route_path
    return None


def _is_allowed_missing_route_claim(claim: RouteClaim) -> bool:
    """
    Plans may legitimately mention routes that do not exist *yet* (to be created).
    To prevent ambiguity, missing routes must be explicitly annotated.

    Allowed annotations (same line):
      - [NEW]      : planned new backend route
      - [FRONTEND] : frontend-only route (Next.js/app router)
      - [EXTERNAL] : third-party URL/path
      - [DEAD]     : route string is referenced for cleanup/analysis but is not mounted in the live app
    """
    text = claim.line_text or ""
    if any(tag in text for tag in ("[NEW]", "[FRONTEND]", "[EXTERNAL]", "[DEAD]")):
        return True
    # Heuristic allow: explicit frontend navigation language.
    return bool(re.search(r"(?i)\bnavigate\s+to\b", text))


def run(
    plan_file: Path, project_root: Path, *, include_sources: bool = False
) -> tuple[int, list[str]]:
    plan_text = plan_file.read_text(encoding="utf-8", errors="replace")
    claims = extract_route_claims(plan_text)
    if not claims:
        return 0, []

    idx = build_route_index(project_root)

    failures: list[str] = []
    hard_fail = False
    for c in claims:
        hit = match_claim(c.path, idx)
        if hit is None:
            if _is_allowed_missing_route_claim(c):
                if include_sources:
                    failures.append(
                        f"{plan_file}:{c.line}: ALLOWED-MISSING '{c.path}' ({c.source})"
                    )
            else:
                failures.append(
                    f"{plan_file}:{c.line}: missing route claim '{c.path}' ({c.source})"
                )
                hard_fail = True
            continue
        if include_sources:
            failures.append(f"{plan_file}:{c.line}: OK '{c.path}' -> '{hit}'")
    return (1 if hard_fail else 0), failures


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Validate plan-claimed route paths against FastAPI source decorators."
    )
    p.add_argument(
        "--plan-file", "-f", type=Path, required=True, help="Path to plan markdown file."
    )
    p.add_argument(
        "--project-root",
        type=Path,
        default=PROJECT_ROOT_DEFAULT,
        help="Project root (default: repo root).",
    )
    p.add_argument("--show-ok", action="store_true", help="Also print OK matches (noisy).")
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        plan_file = args.plan_file.resolve()
        project_root = args.project_root.resolve()
        if not plan_file.exists():
            print(f"ERROR: plan file not found: {plan_file}", file=sys.stderr)
            return 2
        rc, lines = run(plan_file, project_root, include_sources=args.show_ok)
        for line in lines:
            print(line)
        return rc
    except Exception as exc:
        print(f"ERROR: route parity check failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
