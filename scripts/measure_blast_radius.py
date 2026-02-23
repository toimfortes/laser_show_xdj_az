#!/usr/bin/env python3
"""measure_blast_radius.py — Estimate change impact for photonic-synesthesia.

Given a target file or module, uses the code catalog import graph to determine
which other modules would be affected by changes to it. Useful for triaging
which tests to run and which reviewers to alert for a given change.

Usage:
    python scripts/measure_blast_radius.py <target> [--project-root PATH] [--max-depth N]

    <target> can be:
      - A relative file path:  src/photonic_synesthesia/core/state.py
      - A module name:          photonic_synesthesia.core.state
      - An absolute path

Prerequisites:
    data/code_catalog.json must exist (run scripts/build_code_registry.py first).

Exit codes:
    0 = success
    1 = target not found in catalog or catalog missing
    2 = internal error
"""
from __future__ import annotations

import argparse
import json
import sys
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
# Catalog loading
# ---------------------------------------------------------------------------

def load_catalog(root: Path) -> dict[str, Any] | None:
    catalog_path = root / "data" / "code_catalog.json"
    if not catalog_path.exists():
        print(
            f"[measure_blast_radius] ERROR: code catalog not found at {catalog_path}",
            file=sys.stderr,
        )
        print(
            "[measure_blast_radius] Run: python scripts/build_code_registry.py",
            file=sys.stderr,
        )
        return None
    try:
        data = json.loads(catalog_path.read_text())
    except json.JSONDecodeError as exc:
        print(
            f"[measure_blast_radius] ERROR: invalid JSON in {catalog_path}: {exc}",
            file=sys.stderr,
        )
        return None
    if not isinstance(data, dict):
        print(
            f"[measure_blast_radius] ERROR: expected object in {catalog_path}",
            file=sys.stderr,
        )
        return None
    return data


# ---------------------------------------------------------------------------
# Target resolution
# ---------------------------------------------------------------------------

def resolve_target(target_arg: str, root: Path, modules: list[dict[str, Any]]) -> str | None:
    """Normalize target to the 'file' key used in the catalog."""
    known_files: set[str] = set()
    known_modules: dict[str, str] = {}
    for module in modules:
        file_name = module.get("file")
        module_name = module.get("module")
        if isinstance(file_name, str):
            known_files.add(file_name)
            if isinstance(module_name, str):
                known_modules[module_name] = file_name

    # 1. Exact file match
    if target_arg in known_files:
        return target_arg

    # 2. Module name match
    if target_arg in known_modules:
        return known_modules[target_arg]

    # 3. Try as path (absolute or relative to root) -> normalize to relative
    p = Path(target_arg)
    if p.is_absolute():
        try:
            rel = str(p.relative_to(root))
        except ValueError:
            rel = target_arg
    else:
        try:
            rel = str((root / p).resolve().relative_to(root))
        except ValueError:
            rel = target_arg

    if rel in known_files:
        return rel

    # 4. Suffix match (partial path)
    matches: list[str] = [f for f in known_files if f.endswith(rel) or rel.endswith(f)]
    if len(matches) == 1:
        print(
            f"[measure_blast_radius] Resolved '{target_arg}' -> '{matches[0]}'",
            file=sys.stderr,
        )
        return matches[0]
    if len(matches) > 1:
        print(
            f"[measure_blast_radius] Ambiguous target '{target_arg}', matches: {matches}",
            file=sys.stderr,
        )
        return matches[0]

    return None


# ---------------------------------------------------------------------------
# Import graph construction
# ---------------------------------------------------------------------------

def build_reverse_import_graph(modules: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Build a map: file -> list of files that import it (direct dependents)."""
    name_to_file: dict[str, str] = {}
    imported_by: dict[str, list[str]] = {}
    for module in modules:
        file_name = module.get("file")
        module_name = module.get("module")
        if isinstance(file_name, str):
            imported_by[file_name] = []
            if isinstance(module_name, str):
                name_to_file[module_name] = file_name

    for module in modules:
        source_file = module.get("file")
        if not isinstance(source_file, str):
            continue
        raw_imports = module.get("imports", [])
        imports = raw_imports if isinstance(raw_imports, list) else []
        for imp in imports:
            if not isinstance(imp, str):
                continue
            # Find all catalog modules whose name matches this import
            # (exact match or the import is a sub-module of the catalog module)
            for mod_name, mod_file in name_to_file.items():
                if mod_file == source_file:
                    continue
                if mod_name == imp or imp.startswith(mod_name + ".") or mod_name.startswith(imp + "."):
                    if mod_file in imported_by:
                        dependents = imported_by[mod_file]
                        if source_file not in dependents:
                            dependents.append(source_file)

    return imported_by


# ---------------------------------------------------------------------------
# BFS blast radius computation
# ---------------------------------------------------------------------------

def compute_blast_radius(
    target_file: str,
    imported_by: dict[str, list[str]],
    max_depth: int = 5,
) -> dict[str, Any]:
    """BFS from target to find all transitively affected files."""
    # depth_map: file -> shallowest depth at which it was reached
    depth_map: dict[str, int] = {target_file: 0}
    levels: dict[int, list[str]] = {0: [target_file]}
    frontier = {target_file}

    for depth in range(1, max_depth + 1):
        next_frontier: set[str] = set()
        for f in frontier:
            for dependent in imported_by.get(f, []):
                if dependent not in depth_map:
                    depth_map[dependent] = depth
                    next_frontier.add(dependent)
        levels[depth] = sorted(next_frontier)
        frontier = next_frontier
        if not frontier:
            break

    affected = sorted(f for f in depth_map if f != target_file)
    direct = levels.get(1, [])

    return {
        "target": target_file,
        "direct_dependents": direct,
        "transitive_dependents": affected,
        "total_affected": len(affected),
        "max_depth_searched": max_depth,
        "depth_map": {k: v for k, v in depth_map.items() if k != target_file},
        "levels": {str(k): v for k, v in levels.items() if k > 0 and v},
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure the blast radius (change impact) of a source file."
    )
    parser.add_argument(
        "target",
        help="Target file or module to analyze (relative path, absolute path, or module name)",
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="Project root directory (default: auto-detected via pyproject.toml)",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=5,
        help="Maximum transitive dependency depth to explore (default: 5)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(args.project_root).resolve() if args.project_root else _find_project_root()

    catalog = load_catalog(root)
    if catalog is None:
        sys.exit(1)

    modules: list[dict[str, Any]] = catalog.get("modules", [])
    target = resolve_target(args.target, root, modules)

    if target is None:
        known = sorted(m["file"] for m in modules)
        print(
            f"[measure_blast_radius] ERROR: '{args.target}' not found in catalog "
            f"({len(known)} modules known).",
            file=sys.stderr,
        )
        # Emit partial result for pipeline robustness
        print(
            json.dumps(
                {
                    "error": f"target '{args.target}' not found in catalog",
                    "target": args.target,
                    "direct_dependents": [],
                    "transitive_dependents": [],
                    "total_affected": 0,
                }
            )
        )
        sys.exit(1)

    print(f"[measure_blast_radius] Analyzing blast radius for: {target}", file=sys.stderr)
    imported_by = build_reverse_import_graph(modules)
    result = compute_blast_radius(target, imported_by, max_depth=args.max_depth)

    print(
        f"[measure_blast_radius] Direct: {len(result['direct_dependents'])}, "
        f"Transitive: {result['total_affected']}",
        file=sys.stderr,
    )

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
