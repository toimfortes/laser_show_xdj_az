#!/usr/bin/env python3
"""check_patterns.py — Project pattern enforcement for photonic-synesthesia.

Loads best_practices/patterns.json and scans source files for pattern
violations. Emits a JSON array of findings to stdout (pure JSON only —
no other text may appear on stdout).

Usage:
    python scripts/check_patterns.py [--project-root PATH]

Exit codes:
    0 = no violations found
    1 = violations found
    2 = internal error (schema/config problem)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Project root detection
# ---------------------------------------------------------------------------

def _find_project_root() -> Path:
    """Walk up from this script until we find pyproject.toml."""
    here = Path(__file__).resolve()
    for candidate in [here.parent, here.parent.parent]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    return here.parent.parent


# ---------------------------------------------------------------------------
# Stderr-only diagnostic helper (stdout is reserved for JSON)
# ---------------------------------------------------------------------------

def _err(msg: str) -> None:
    print(f"[check_patterns] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Pattern loading
# ---------------------------------------------------------------------------

def load_patterns(root: Path) -> list[dict[str, Any]]:
    """Load pattern definitions from best_practices/patterns.json."""
    patterns_file = root / "best_practices" / "patterns.json"
    if not patterns_file.exists():
        _err(f"WARNING: patterns.json not found at {patterns_file} — no patterns to check.")
        return []
    try:
        data = json.loads(patterns_file.read_text())
    except json.JSONDecodeError as exc:
        _err(f"ERROR: Failed to parse patterns.json: {exc}")
        return []
    if not isinstance(data, dict):
        _err("ERROR: patterns.json root must be an object with a 'patterns' key")
        return []
    raw_patterns = data.get("patterns", [])
    if not isinstance(raw_patterns, list):
        _err("ERROR: patterns.json 'patterns' must be a list")
        return []

    patterns: list[dict[str, Any]] = []
    for item in raw_patterns:
        if isinstance(item, dict):
            patterns.append(item)
    _err(f"Loaded {len(patterns)} patterns from {patterns_file.relative_to(root)}")
    return patterns


# ---------------------------------------------------------------------------
# File globbing
# ---------------------------------------------------------------------------

def _expand_globs(root: Path, globs: list[str]) -> list[Path]:
    result: list[Path] = []
    for g in globs:
        result.extend(root.glob(g))
    return sorted(set(result))


# ---------------------------------------------------------------------------
# Check implementations
# ---------------------------------------------------------------------------

def _make_finding(
    pattern: dict[str, Any],
    file: str,
    line: int | None,
    evidence: str,
) -> dict[str, Any]:
    return {
        "id": pattern["id"],
        "severity": pattern.get("severity", "medium"),
        "category": pattern.get("category", "patterns"),
        "file": file,
        "line": line,
        "column": None,
        "message": pattern.get("message", "Pattern violation"),
        "evidence": evidence.strip(),
        "remediation": pattern.get("remediation", ""),
        "rule_id": pattern["id"],
        "confidence": "high",
    }


def check_grep(
    root: Path,
    pattern: dict[str, Any],
    regex: str,
    file_globs: list[str],
    exclude_globs: list[str],
) -> list[dict[str, Any]]:
    """Search for regex matches across files; each match becomes a finding."""
    findings: list[dict[str, Any]] = []

    exclude_paths: set[Path] = set()
    for eg in exclude_globs:
        exclude_paths.update(root.glob(eg))

    try:
        compiled = re.compile(regex)
    except re.error as exc:
        _err(f"ERROR: Pattern {pattern['id']}: invalid regex '{regex}': {exc}")
        return []

    for path in _expand_globs(root, file_globs):
        if not path.is_file():
            continue
        if path in exclude_paths:
            continue
        try:
            lines = path.read_text(errors="replace").splitlines()
        except OSError as exc:
            _err(f"WARNING: Cannot read {path}: {exc}")
            continue
        for lineno, line in enumerate(lines, 1):
            if compiled.search(line):
                rel = str(path.relative_to(root))
                findings.append(_make_finding(pattern, rel, lineno, line))

    return findings


def check_absent(
    root: Path,
    pattern: dict[str, Any],
    needle: str,
    file_globs: list[str],
) -> list[dict[str, Any]]:
    """Check that needle IS present in each matched file; report if absent."""
    findings: list[dict[str, Any]] = []
    matched_files = _expand_globs(root, file_globs)

    if not matched_files:
        # No files matched the glob — the file itself is missing
        for g in file_globs:
            findings.append(
                _make_finding(
                    pattern,
                    g,
                    None,
                    f"No files matched glob '{g}' — cannot verify presence of '{needle}'",
                )
            )
        return findings

    for path in matched_files:
        if not path.is_file():
            continue
        try:
            content = path.read_text(errors="replace")
        except OSError as exc:
            _err(f"WARNING: Cannot read {path}: {exc}")
            continue
        if needle not in content:
            rel = str(path.relative_to(root))
            findings.append(
                _make_finding(
                    pattern,
                    rel,
                    None,
                    f"Required token '{needle}' not found in file.",
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Main check dispatcher
# ---------------------------------------------------------------------------

def run_checks(root: Path, patterns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    all_findings: list[dict[str, Any]] = []

    for pat in patterns:
        check_type = pat.get("check_type", "grep")
        file_globs: list[str] = pat.get("files", [])
        if isinstance(file_globs, str):
            file_globs = [file_globs]
        exclude_globs: list[str] = pat.get("exclude", [])
        if isinstance(exclude_globs, str):
            exclude_globs = [exclude_globs]

        if check_type == "grep":
            findings = check_grep(root, pat, pat["pattern"], file_globs, exclude_globs)
        elif check_type == "absent":
            findings = check_absent(root, pat, pat["pattern"], file_globs)
        else:
            _err(f"WARNING: Unknown check_type '{check_type}' for pattern {pat.get('id')} — skipping.")
            findings = []

        if findings:
            _err(f"  {pat['id']}: {len(findings)} finding(s)")
        all_findings.extend(findings)

    return all_findings


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check project coding patterns. Emits findings as a JSON array to stdout."
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Compatibility flag (all checks already run by default).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Compatibility flag (output is JSON by default).",
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="Project root directory (default: auto-detected via pyproject.toml)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(args.project_root).resolve() if args.project_root else _find_project_root()
    _err(f"Project root: {root}")

    patterns = load_patterns(root)
    if not patterns:
        # No patterns configured — emit empty findings array and exit clean
        print(json.dumps([], indent=2))
        sys.exit(0)

    findings = run_checks(root, patterns)
    _err(f"Total findings: {len(findings)}")

    # Emit PURE JSON to stdout — this is the only stdout output
    print(json.dumps(findings, indent=2))
    sys.exit(1 if findings else 0)


if __name__ == "__main__":
    main()
