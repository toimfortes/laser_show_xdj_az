#!/usr/bin/env python3
"""Forensic Lint — Automated pre-verdict mechanical checks.

Checks plan receipt tables against evidence.jsonl for:
- Receipt ID concordance (R50/RULE 91)
- Row-atomic field completeness (R39/RULE 80)
- Full-length SHA-256 hashes (R44/RULE 85)
- Mixed-exit stability proof (R46/RULE 87)
- Command parity (R37/RULE 82)
- GO/STOP consistency (R40/RULE 81)

Usage:
    python scripts/forensic_lint.py plans/remediation_plan_20260214_audit.md

Exit codes:
    0 = all checks pass
    1 = hard-fail (plan cannot be GO)
    2 = warnings only
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


def load_evidence(evidence_path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    with open(evidence_path) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def extract_plan_receipt_rows(plan_path: Path) -> list[dict[str, Any]]:
    """Extract receipt rows from the plan's markdown table."""
    lines = plan_path.read_text().splitlines()
    rows: list[dict[str, Any]] = []
    in_receipt_table = False
    headers: list[str] = []

    for line in lines:
        stripped = line.strip()

        # Detect the evidence receipts table
        if "Evidence Receipts" in stripped and "Row-Atomic" in stripped:
            in_receipt_table = True
            continue

        if in_receipt_table:
            if stripped.startswith("|") and "---" not in stripped:
                cells = [c.strip().strip("`") for c in stripped.split("|")[1:-1]]
                if not headers:
                    headers = [h.lower().replace(" ", "_").replace("-", "_") for h in cells]
                else:
                    if len(cells) >= len(headers):
                        row = dict(zip(headers, cells, strict=False))
                        rows.append(row)
            elif stripped and not stripped.startswith("|"):
                # End of table
                if headers and rows:
                    break

    return rows


def extract_plan_status(plan_path: Path) -> str:
    text = plan_path.read_text()
    if "**STATUS: GO**" in text:
        return "GO"
    elif "**STATUS: STOP**" in text:
        return "STOP"
    return "UNKNOWN"


def check_id_concordance(
    plan_rows: list[dict[str, Any]], evidence: list[dict[str, Any]]
) -> list[str]:
    """R50/RULE 91: Plan receipt IDs must match evidence.jsonl IDs."""
    failures: list[str] = []
    evidence_ids = {e["id"] for e in evidence}

    for row in plan_rows:
        rid = row.get("id", "")
        if rid and rid not in evidence_ids:
            # Check if it's a close match (drift)
            close = [
                eid
                for eid in evidence_ids
                if eid.replace("-", "") == rid.replace("-", "") or rid in eid or eid in rid
            ]
            if close:
                failures.append(
                    f"HARD-FAIL [R50]: Plan receipt ID '{rid}' not in evidence.jsonl. "
                    f"Close matches: {close}. ID concordance drift."
                )
            else:
                failures.append(
                    f"HARD-FAIL [R50]: Plan receipt ID '{rid}' has no matching "
                    f"evidence.jsonl entry."
                )
    return failures


def check_row_atomic(plan_rows: list[dict[str, Any]]) -> list[str]:
    """R39/RULE 80: Every receipt row must have all required fields."""
    failures: list[str] = []
    required = {"id", "command", "cwd", "rc"}
    # Hash fields may have varying header names
    hash_patterns = ["stdout", "stderr", "sha"]

    for row in plan_rows:
        keys = set(row.keys())
        missing = required - keys
        if missing:
            failures.append(
                f"HARD-FAIL [R39]: Receipt '{row.get('id', '?')}' missing "
                f"row-atomic fields: {missing}"
            )

        # Check for hash fields
        has_hash = any(any(p in k for p in hash_patterns) for k in keys)
        if not has_hash:
            failures.append(
                f"HARD-FAIL [R44]: Receipt '{row.get('id', '?')}' missing hash columns."
            )
    return failures


def check_hash_length(plan_rows: list[dict[str, Any]]) -> list[str]:
    """R44/RULE 85: All SHA-256 hashes must be exactly 64 hex chars."""
    failures: list[str] = []
    sha_pattern = re.compile(r"^[a-f0-9]+$")

    for row in plan_rows:
        for key, value in row.items():
            if "sha" in key.lower() or "hash" in key.lower():
                val = value.strip().strip("`")
                if val and val != "_pending_" and sha_pattern.match(val) and len(val) != 64:
                    failures.append(
                        f"HARD-FAIL [R44]: Receipt '{row.get('id', '?')}' "
                        f"field '{key}' has truncated hash ({len(val)} chars, "
                        f"need 64): {val[:20]}..."
                    )
    return failures


def check_mixed_exit_stability(evidence: list[dict[str, Any]]) -> list[str]:
    """R46/RULE 87: Gates with mixed rc need 3-pass stability proof."""
    failures: list[str] = []
    gate_results: dict[str, list[int | None]] = defaultdict(list)

    for entry in evidence:
        # Group by base command (normalize)
        cmd = entry.get("cmd", "")
        rc = entry.get("rc")
        gate_results[cmd].append(rc)

    for cmd, rcs in gate_results.items():
        if len(set(rcs)) > 1:
            # Mixed exit codes — need at least 3 consecutive passes
            pass_count = sum(1 for r in rcs if r == 0)
            if pass_count < 3:
                failures.append(
                    f"HARD-FAIL [R46]: Gate '{cmd[:60]}...' has mixed exit "
                    f"codes {rcs} but only {pass_count} passes (need 3)."
                )
    return failures


def check_command_parity(
    plan_rows: list[dict[str, Any]], evidence: list[dict[str, Any]]
) -> list[str]:
    """R37/RULE 82: Plan gate command must match evidence command."""
    failures: list[str] = []
    evidence_by_id = {e["id"]: e for e in evidence}

    for row in plan_rows:
        rid = row.get("id", "")
        cmd = row.get("command", "")
        if rid in evidence_by_id:
            ev_cmd = evidence_by_id[rid].get("cmd", "")
            if cmd and ev_cmd and cmd != ev_cmd:
                failures.append(
                    f"HARD-FAIL [R37]: Receipt '{rid}' command mismatch.\n"
                    f"  Plan:     {cmd}\n"
                    f"  Evidence: {ev_cmd}"
                )
    return failures


def check_go_consistency(
    plan_status: str, evidence: list[dict[str, Any]], plan_rows: list[dict[str, Any]]
) -> list[str]:
    """R40/RULE 81: If any mandatory gate has rc≠0 latest, can't be GO."""
    failures: list[str] = []
    if plan_status != "GO":
        return failures

    # Get latest evidence entry per ID
    latest: dict[str, dict[str, Any]] = {}
    for entry in evidence:
        eid = entry["id"]
        latest[eid] = entry  # later entries overwrite earlier

    # Check plan receipt IDs
    for row in plan_rows:
        rid = row.get("id", "")
        if rid in latest and latest[rid].get("rc") != 0:
            failures.append(
                f"HARD-FAIL [R40]: Plan is GO but gate '{rid}' has "
                f"rc={latest[rid]['rc']} in latest evidence."
            )

    return failures


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/forensic_lint.py <plan_file>")
        sys.exit(2)

    plan_path = Path(sys.argv[1])
    evidence_path = Path("evidence.jsonl")

    if not plan_path.exists():
        print(f"ERROR: Plan file not found: {plan_path}")
        sys.exit(2)
    if not evidence_path.exists():
        print("ERROR: evidence.jsonl not found")
        sys.exit(2)

    evidence = load_evidence(evidence_path)
    plan_rows = extract_plan_receipt_rows(plan_path)
    plan_status = extract_plan_status(plan_path)

    print("Forensic Lint v1.0")
    print(f"  Plan: {plan_path}")
    print(f"  Status: {plan_status}")
    print(f"  Receipt rows: {len(plan_rows)}")
    print(f"  Evidence entries: {len(evidence)}")
    print()

    all_failures: list[str] = []
    warnings: list[str] = []

    # Run all checks
    all_failures.extend(check_id_concordance(plan_rows, evidence))
    all_failures.extend(check_row_atomic(plan_rows))
    all_failures.extend(check_hash_length(plan_rows))
    all_failures.extend(check_mixed_exit_stability(evidence))
    all_failures.extend(check_command_parity(plan_rows, evidence))
    all_failures.extend(check_go_consistency(plan_status, evidence, plan_rows))

    # Print results
    if all_failures:
        print(f"RESULT: {len(all_failures)} HARD-FAIL(s)")
        print()
        for f in all_failures:
            print(f"  {f}")
        print()
        print("Verdict: STOP (mechanical forensic failures)")
        sys.exit(1)
    elif warnings:
        print(f"RESULT: {len(warnings)} WARNING(s)")
        for w in warnings:
            print(f"  {w}")
        sys.exit(2)
    else:
        print("RESULT: ALL CHECKS PASS")
        print("Verdict: No mechanical forensic issues detected.")
        sys.exit(0)


if __name__ == "__main__":
    main()
