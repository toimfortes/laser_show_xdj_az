#!/usr/bin/env python3
"""build_code_registry.py — Build the project code catalog for photonic-synesthesia.

Scans src/ using the standard library ast module to catalog every Python
module, class, function, and their import dependencies. Writes the catalog
to data/code_catalog.json for use by blast-radius analysis and other tooling.

Usage:
    python scripts/build_code_registry.py [--project-root PATH] [--output PATH]

Exit codes:
    0 = success
    1 = error
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Project root detection
# ---------------------------------------------------------------------------

def _find_project_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in [here.parent, here.parent.parent]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    return here.parent.parent


# ---------------------------------------------------------------------------
# AST-based module info extraction
# ---------------------------------------------------------------------------

def _module_name_from_path(path: Path, src_dir: Path) -> str:
    """Convert src/foo/bar/baz.py -> foo.bar.baz"""
    try:
        rel = path.relative_to(src_dir)
    except ValueError:
        rel = path
    parts = list(rel.parts)
    if parts and parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def extract_module_info(path: Path, root: Path, src_dir: Path) -> dict[str, Any]:
    """Parse a Python file with ast and return its catalog entry."""
    rel = str(path.relative_to(root))
    module_name = _module_name_from_path(path, src_dir)

    try:
        source = path.read_text(errors="replace")
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return {
            "file": rel,
            "module": module_name,
            "parse_error": str(exc),
            "classes": [],
            "functions": [],
            "imports": [],
            "lines": 0,
        }

    classes: list[dict[str, Any]] = []
    functions: list[dict[str, Any]] = []
    imports: list[str] = []

    # Top-level definitions only (col_offset == 0)
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            methods = [
                n.name
                for n in ast.iter_child_nodes(node)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            bases = []
            for b in node.bases:
                try:
                    bases.append(ast.unparse(b))
                except Exception:
                    bases.append("<unknown>")
            classes.append(
                {
                    "name": node.name,
                    "line": node.lineno,
                    "methods": methods,
                    "bases": bases,
                }
            )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(
                {
                    "name": node.name,
                    "line": node.lineno,
                    "async": isinstance(node, ast.AsyncFunctionDef),
                }
            )

    # Collect all imports (for dependency graph)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)

    source_lines = source.count("\n") + 1

    return {
        "file": rel,
        "module": module_name,
        "classes": classes,
        "functions": functions,
        "imports": sorted(set(imports)),
        "lines": source_lines,
    }


# ---------------------------------------------------------------------------
# Catalog builder
# ---------------------------------------------------------------------------

def build_catalog(root: Path) -> dict[str, Any]:
    src_dir = root / "src"
    if not src_dir.is_dir():
        print(f"[build_code_registry] WARNING: src/ not found at {src_dir}", file=sys.stderr)

    py_files = sorted(src_dir.rglob("*.py")) if src_dir.is_dir() else []
    modules: list[dict[str, Any]] = []

    for path in py_files:
        info = extract_module_info(path, root, src_dir)
        modules.append(info)
        print(f"  indexed: {info['file']}", file=sys.stderr)

    total_lines = sum(m.get("lines", 0) for m in modules)
    total_classes = sum(len(m.get("classes", [])) for m in modules)
    total_functions = sum(len(m.get("functions", [])) for m in modules)

    return {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_root": str(root),
        "total_modules": len(modules),
        "total_lines": total_lines,
        "total_classes": total_classes,
        "total_functions": total_functions,
        "modules": modules,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build project code registry / catalog for blast-radius analysis."
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="Project root directory (default: auto-detected via pyproject.toml)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output path for catalog JSON (default: data/code_catalog.json)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(args.project_root).resolve() if args.project_root else _find_project_root()
    out_path = (
        Path(args.output).resolve() if args.output else root / "data" / "code_catalog.json"
    )

    print(f"[build_code_registry] Project root: {root}", file=sys.stderr)
    print(f"[build_code_registry] Output: {out_path}", file=sys.stderr)

    catalog = build_catalog(root)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(catalog, indent=2))

    print(
        f"[build_code_registry] Wrote catalog: "
        f"{catalog['total_modules']} modules, "
        f"{catalog['total_classes']} classes, "
        f"{catalog['total_functions']} functions, "
        f"{catalog['total_lines']} lines -> {out_path}",
        file=sys.stderr,
    )
    # Emit summary JSON to stdout for pipeline consumption
    print(
        json.dumps(
            {
                "status": "ok",
                "output": str(out_path),
                "total_modules": catalog["total_modules"],
                "total_classes": catalog["total_classes"],
                "total_functions": catalog["total_functions"],
                "total_lines": catalog["total_lines"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
