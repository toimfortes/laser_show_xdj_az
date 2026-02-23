#!/usr/bin/env python3
"""
Plan preflight checker referenced by docs/reference/critique_implementation.md.

This is intentionally conservative: it enforces the "Exists" and "Route Reality"
basics and provides a fast signal for common STOP conditions (missing tools).

Exit codes:
- 0: PASS (or PASS with warnings)
- 1: FAIL (hard issues that should block a PASS/GO recommendation)
- 2: ERROR (unexpected failure)
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str  # "WARN" | "FAIL"
    detail: str


def _run(cmd: list[str], cwd: Path) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def _has_integration_contracts(plan_text: str) -> bool:
    return bool(re.search(r"(?i)\bintegration\s+contract\b", plan_text))


def _plan_mentions_boundaries(plan_text: str) -> bool:
    # Heuristic: only enforce integration contracts when the plan is discussing boundary work.
    keywords = [
        "caller",
        "callee",
        "request->",
        "request →",
        "response_model",
        "jwt",
        "idor",
        "ownership",
        "route reality",
        "include_router",
    ]
    lower = plan_text.lower()
    return any(k in lower for k in keywords)


def check(plan_file: Path, project_root: Path, checks: set[str]) -> tuple[int, list[Finding]]:
    findings: list[Finding] = []

    if not plan_file.exists():
        findings.append(Finding("P0", "FAIL", f"Plan file not found: {plan_file}"))
        return 1, findings

    if "exists" in checks:
        required_files = [
            project_root / "docs" / "reference" / "critique_implementation.md",
            project_root / "scripts" / "audit" / "boundary_contract_template.md",
            project_root / "scripts" / "audit" / "route_parity_check.py",
        ]
        for f in required_files:
            if not f.exists():
                findings.append(Finding("P1", "FAIL", f"Missing required framework file: {f}"))

    plan_text = plan_file.read_text(encoding="utf-8", errors="replace")

    # V105-ish enforcement: only when the plan is actually doing boundary work.
    if (
        "integration" in checks
        and _plan_mentions_boundaries(plan_text)
        and not _has_integration_contracts(plan_text)
    ):
        findings.append(
            Finding(
                "P2",
                "FAIL",
                "Plan discusses boundary work but contains no 'Integration Contract' blocks.",
            )
        )

    if "routes" in checks:
        # V106 enforcement: route parity check (best-effort; empty route claims should PASS).
        route_checker = project_root / "scripts" / "audit" / "route_parity_check.py"
        if route_checker.exists():
            rc, out, err = _run(
                [
                    sys.executable,
                    str(route_checker),
                    "--plan-file",
                    str(plan_file),
                    "--project-root",
                    str(project_root),
                ],
                cwd=project_root,
            )
            if rc == 2:
                findings.append(
                    Finding(
                        "P3", "FAIL", f"route_parity_check error:\n{err.strip() or out.strip()}"
                    )
                )
            elif rc == 1:
                findings.append(
                    Finding("P3", "FAIL", "route_parity_check reported parity failures")
                )
            else:
                # PASS
                pass
        else:
            findings.append(
                Finding("P3", "WARN", "route_parity_check.py not present; skipping V106 preflight")
            )

    hard_fails = [f for f in findings if f.severity == "FAIL"]
    return (1 if hard_fails else 0), findings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plan preflight checks (Exists + Route Reality + Contracts)."
    )
    parser.add_argument(
        "--plan-file", type=Path, required=True, help="Path to the plan markdown file."
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path("."),
        help="Project root (default: .)",
    )
    parser.add_argument(
        "--check",
        action="append",
        choices=["exists", "integration", "routes"],
        default=None,
        help=(
            "Optional checks to run (repeatable). If omitted, runs all checks. "
            "Supported: exists, integration, routes."
        ),
    )
    args = parser.parse_args()
    try:
        project_root = args.project_root.resolve()
        plan_file = args.plan_file
        if not plan_file.is_absolute():
            plan_file = (project_root / plan_file).resolve()

        # Backward compatible: if no --check flags were passed, run everything.
        requested = set(args.check or ["exists", "integration", "routes"])

        rc, findings = check(plan_file, project_root, requested)

        print("PLAN PREFLIGHT")
        print(f"plan: {plan_file}")
        print(f"root: {project_root}")
        print(f"checks: {', '.join(sorted(requested))}")
        if findings:
            for f in findings:
                print(f"{f.severity} {f.code}: {f.detail}")
        else:
            print("PASS: no findings")
        return rc
    except Exception as exc:  # pragma: no cover
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
