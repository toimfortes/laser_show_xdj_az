import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import jsonschema

ROOT = Path(__file__).resolve().parents[2]


def to_abs(path_str: str) -> Path:
    path = Path(path_str)
    if path.is_absolute():
        return path
    return ROOT / path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run deterministic critique preflight checks.")
    parser.add_argument(
        "--agent-tag",
        help="Agent/run suffix for isolated artifacts (e.g., codex, claude, gemini, agent_1).",
    )
    parser.add_argument("--spec-path", help="Path to critique spec JSON.")
    parser.add_argument("--schema-path", help="Path to critique schema JSON.")
    parser.add_argument("--matter-map-path", help="Path to matter map JSON.")
    parser.add_argument("--evidence-path", help="Path to output evidence JSONL.")
    return parser.parse_args()


def resolve_paths(
    args: argparse.Namespace,
) -> tuple[Path, Path, Path, Path]:
    tag = (args.agent_tag or "").strip()

    schema_raw = args.schema_path or os.environ.get(
        "SCHEMA_PATH", "schemas/critique_spec.schema.json"
    )
    schema_path = to_abs(schema_raw)

    if args.spec_path:
        spec_path = to_abs(args.spec_path)
    elif os.environ.get("SPEC_PATH"):
        spec_path = to_abs(os.environ["SPEC_PATH"])
    elif tag and to_abs(f"schemas/critique_spec_{tag}.json").exists():
        spec_path = to_abs(f"schemas/critique_spec_{tag}.json")
    else:
        spec_path = to_abs("schemas/critique_spec.json")

    if args.matter_map_path:
        matter_map_path = to_abs(args.matter_map_path)
    elif os.environ.get("MATTER_MAP_PATH"):
        matter_map_path = to_abs(os.environ["MATTER_MAP_PATH"])
    elif tag:
        matter_map_path = to_abs(f"matter_map_{tag}.json")
    else:
        matter_map_path = to_abs("matter_map.json")

    if args.evidence_path:
        evidence_path = to_abs(args.evidence_path)
    elif os.environ.get("EVIDENCE_PATH"):
        evidence_path = to_abs(os.environ["EVIDENCE_PATH"])
    elif tag:
        evidence_path = to_abs(f"evidence_{tag}.jsonl")
    else:
        evidence_path = to_abs("evidence.jsonl")

    return spec_path, schema_path, matter_map_path, evidence_path


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}, got {type(data).__name__}")
    return cast(dict[str, Any], data)


def run_cmd(cmd: list[str], cwd: Path) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def record(
    check: str,
    status: str,
    enforcement: str,
    detail: str,
    **kwargs: Any,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "check": check,
        "status": status,
        "enforcement": enforcement,
        "detail": detail,
        "timestamp": now_utc(),
    }
    item.update(kwargs)
    return item


def iter_non_code_lines(text: str, exclude_code_fences: bool = True) -> list[tuple[int, str]]:
    lines = text.splitlines()
    in_fence = False
    out: list[tuple[int, str]] = []

    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if exclude_code_fences and in_fence:
            continue
        out.append((idx, line))
    return out


def check_schema(spec: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    try:
        jsonschema.validate(spec, schema)
        return record("SCHEMA", "PASS", "hard-mandatory", "Manifest validates against schema")
    except Exception as exc:
        return record("SCHEMA", "FAIL", "hard-mandatory", f"Schema validation error: {exc}")


def check_regex_compile(spec: dict[str, Any]) -> dict[str, Any]:
    compiled = 0
    failures: list[str] = []
    for rule in spec.get("rules", []):
        pattern = rule.get("verify", {}).get("pattern")
        if pattern:
            try:
                re.compile(pattern)
                compiled += 1
            except re.error as exc:
                failures.append(f"{rule.get('id', 'UNKNOWN')}: {exc}")
    if failures:
        return record(
            "REGEX-COMPILE",
            "FAIL",
            "hard-mandatory",
            "Invalid regex pattern(s) in manifest",
            failures=failures,
        )
    return record(
        "REGEX-COMPILE",
        "PASS",
        "hard-mandatory",
        f"Compiled {compiled} regex pattern(s) from manifest",
    )


def check_file_existence(scope_files: list[str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for f in scope_files:
        path = ROOT / f
        if path.exists():
            results.append(record("V1", "PASS", "hard-mandatory", "Scope file exists", file=f))
        else:
            results.append(record("V1", "FAIL", "hard-mandatory", "Scope file not found", file=f))
    return results


def check_matrix(scope_files: list[str], matrix: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    scope_set = set(scope_files)

    for vector, file_map in matrix.items():
        if not re.match(r"^V\d+$", vector):
            continue

        keys = {k for k in file_map if k != "_doc"}
        missing = sorted(scope_set - keys)
        extra = sorted(keys - scope_set)
        if missing or extra:
            results.append(
                record(
                    "R13",
                    "FAIL",
                    "hard-mandatory",
                    "Matrix/scope parity mismatch",
                    vector=vector,
                    missing=missing,
                    extra=extra,
                )
            )
            continue

        for file, meta in file_map.items():
            if file == "_doc":
                continue
            status = meta.get("status")
            if status == "missing":
                results.append(
                    record(
                        "R13",
                        "FAIL",
                        "hard-mandatory",
                        "Matrix cell marked missing",
                        vector=vector,
                        file=file,
                    )
                )
            if status == "n/a" and not meta.get("justification"):
                results.append(
                    record(
                        "R13",
                        "FAIL",
                        "hard-mandatory",
                        "n/a matrix cell missing justification",
                        vector=vector,
                        file=file,
                    )
                )

    if not results:
        results.append(
            record("R13", "PASS", "hard-mandatory", "Matrix completeness + parity check passed")
        )
    return results


def check_matter_map_freshness(matter_map: dict[str, Any]) -> dict[str, Any]:
    rc, out, err = run_cmd(["git", "rev-parse", "HEAD"], ROOT)
    if rc != 0:
        return record(
            "R23",
            "UNVERIFIED",
            "hard-mandatory",
            "Unable to read git HEAD",
            command="git rev-parse HEAD",
            exit_code=rc,
            stderr=err.strip(),
        )
    head = out.strip()
    mm_sha = matter_map.get("_meta", {}).get("git_sha")
    if mm_sha == head:
        return record(
            "R23", "PASS", "hard-mandatory", "matter_map git SHA matches HEAD", git_sha=head
        )
    return record(
        "R23",
        "FAIL",
        "hard-mandatory",
        "matter_map git SHA mismatch",
        matter_map_sha=mm_sha,
        head_sha=head,
    )


def check_matter_map_scope_parity(
    scope_files: list[str], matter_map: dict[str, Any]
) -> dict[str, Any]:
    scope_set = set(scope_files)
    map_scope = matter_map.get("_meta", {}).get("scope_files", [])
    map_set = set(map_scope) if isinstance(map_scope, list) else set()

    missing = sorted(scope_set - map_set)
    extra = sorted(map_set - scope_set)
    if not missing and not extra:
        return record(
            "R26",
            "PASS",
            "hard-mandatory",
            "matter_map scope matches manifest scope",
            count=len(scope_set),
        )
    return record(
        "R26",
        "FAIL",
        "hard-mandatory",
        "matter_map scope/manifest scope mismatch",
        missing=missing,
        extra=extra,
        scope_count=len(scope_set),
        map_scope_count=len(map_set),
    )


def check_r02_numeric_methodology(spec: dict[str, Any], plan_text: str) -> dict[str, Any]:
    rule = next((r for r in spec.get("rules", []) if r.get("id") == "R02"), None)
    if not rule:
        return record("R02", "UNVERIFIED", "soft-mandatory", "R02 not present in manifest")

    verify = rule.get("verify", {})
    keywords = [k.lower() for k in verify.get("claim_keywords", [])]
    markers = [m.lower() for m in verify.get("methodology_markers", [])]
    exclude_code = bool(verify.get("exclude_in_code_fences", True))
    exclude_line_patterns = verify.get("exclude_line_patterns", [])
    compiled_excludes = [re.compile(pat) for pat in exclude_line_patterns]

    if not keywords:
        return record(
            "R02",
            "UNVERIFIED",
            rule.get("enforcement", "soft-mandatory"),
            "R02 missing claim_keywords",
        )

    numeric_re = re.compile(r"\b\d+(?:\.\d+)?%?\b")
    offenders: list[dict[str, Any]] = []

    for line_no, line in iter_non_code_lines(plan_text, exclude_code_fences=exclude_code):
        stripped = line.strip()
        if (
            not stripped
            or stripped.startswith("#")
            or stripped == "|"
            or set(stripped) <= {"-", "|", " "}
        ):
            continue
        if any(rx.search(line) for rx in compiled_excludes):
            continue

        lower = line.lower()
        if not numeric_re.search(line):
            continue
        if not any(k in lower for k in keywords):
            continue
        if any(m in lower for m in markers):
            continue
        if "sha256:" in lower:
            continue

        offenders.append({"line": line_no, "text": stripped[:240]})

    if offenders:
        return record(
            "R02",
            "FAIL",
            rule.get("enforcement", "soft-mandatory"),
            "Numeric claims missing methodology in scoped claim lines",
            count=len(offenders),
            samples=offenders[:20],
        )
    return record(
        "R02",
        "PASS",
        rule.get("enforcement", "soft-mandatory"),
        "All scoped numeric claim lines include methodology markers",
    )


def check_r15_ast_vs_regex(
    spec: dict[str, Any], matter_map: dict[str, Any]
) -> list[dict[str, Any]]:
    rule = next((r for r in spec.get("rules", []) if r.get("id") == "R15"), None)
    if not rule:
        return [record("R15", "UNVERIFIED", "hard-mandatory", "R15 not present in manifest")]

    threshold = 10.0
    pass_condition = rule.get("verify", {}).get("pass_condition", "")
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)", pass_condition)
    if m:
        threshold = float(m.group(1))

    results: list[dict[str, Any]] = []
    v84 = spec.get("vector_file_matrix", {}).get("V84", {})
    required_files = [
        f for f, meta in v84.items() if isinstance(meta, dict) and meta.get("status") == "required"
    ]
    if not required_files:
        return [
            record(
                "R15", "UNVERIFIED", "hard-mandatory", "No required files found for V84 in matrix"
            )
        ]

    for file in required_files:
        abs_file = ROOT / file
        if not abs_file.exists():
            results.append(
                record("R15", "FAIL", "hard-mandatory", "V84 required file missing", file=file)
            )
            continue

        mm_entry = matter_map.get(file, {})
        exceptions = mm_entry.get("exceptions", [])
        if isinstance(exceptions, list):
            ast_count = len(
                [e for e in exceptions if isinstance(e, dict) and e.get("type") == "HTTPException"]
            )
        else:
            ast_count = 0

        rc, out, err = run_cmd(["rg", "-n", "raise HTTPException", str(abs_file)], ROOT)
        if rc not in (0, 1):
            results.append(
                record(
                    "R15",
                    "UNVERIFIED",
                    "hard-mandatory",
                    "Regex command failed for V84 cross-check",
                    file=file,
                    command='rg -n "raise HTTPException" <file>',
                    exit_code=rc,
                    stderr=err.strip(),
                )
            )
            continue
        regex_count = 0 if rc == 1 else len([ln for ln in out.splitlines() if ln.strip()])

        denom = max(ast_count, regex_count, 1)
        delta_pct = abs(ast_count - regex_count) * 100.0 / denom

        if delta_pct > threshold:
            results.append(
                record(
                    "R15",
                    "FAIL",
                    "hard-mandatory",
                    "AST/regex divergence exceeds threshold",
                    file=file,
                    ast_count=ast_count,
                    regex_count=regex_count,
                    delta_pct=round(delta_pct, 2),
                    max_divergence_pct=threshold,
                )
            )
        else:
            results.append(
                record(
                    "R15",
                    "PASS",
                    "hard-mandatory",
                    "AST/regex divergence within threshold",
                    file=file,
                    ast_count=ast_count,
                    regex_count=regex_count,
                    delta_pct=round(delta_pct, 2),
                    max_divergence_pct=threshold,
                )
            )
    return results


def write_evidence(items: list[dict[str, Any]], evidence_path: Path) -> None:
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    with evidence_path.open("w", encoding="utf-8") as fh:
        for item in items:
            fh.write(json.dumps(item) + "\n")


def main() -> int:
    args = parse_args()
    spec_path, schema_path, matter_map_path, evidence_path = resolve_paths(args)

    try:
        spec = load_json(spec_path)
        schema = load_json(schema_path)
        matter_map = load_json(matter_map_path)
        plan_path = Path(spec["plan_file"])
        plan_text = plan_path.read_text(encoding="utf-8")
    except Exception as exc:
        print(
            "PREFLIGHT ERROR: failed to load artifacts:",
            f"spec={spec_path} schema={schema_path} map={matter_map_path} evidence={evidence_path} err={exc}",
        )
        return 2

    scope_files = (
        spec.get("scope", {}).get("primary", [])
        + spec.get("scope", {}).get("secondary", [])
        + spec.get("scope", {}).get("tertiary", [])
    )
    evidence: list[dict[str, Any]] = []

    evidence.append(check_schema(spec, schema))
    evidence.append(check_regex_compile(spec))
    evidence.extend(check_file_existence(scope_files))
    evidence.extend(check_matrix(scope_files, spec.get("vector_file_matrix", {})))
    evidence.append(check_matter_map_scope_parity(scope_files, matter_map))
    evidence.append(check_matter_map_freshness(matter_map))
    evidence.append(check_r02_numeric_methodology(spec, plan_text))
    evidence.extend(check_r15_ast_vs_regex(spec, matter_map))

    write_evidence(evidence, evidence_path)

    hard_fails = [
        e
        for e in evidence
        if e.get("enforcement") == "hard-mandatory" and e.get("status") in ("FAIL", "UNVERIFIED")
    ]
    soft_fails = [
        e
        for e in evidence
        if e.get("enforcement") == "soft-mandatory" and e.get("status") in ("FAIL", "UNVERIFIED")
    ]

    if hard_fails:
        print("PREFLIGHT HARD FAILURES:")
        for item in hard_fails:
            print(json.dumps(item, ensure_ascii=False))
        if soft_fails:
            print("PREFLIGHT SOFT FAILURES:")
            for item in soft_fails:
                print(json.dumps(item, ensure_ascii=False))
        return 1

    if soft_fails:
        print("PREFLIGHT PASS (with soft failures):")
        for item in soft_fails:
            print(json.dumps(item, ensure_ascii=False))
        return 0

    print("PREFLIGHT PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
