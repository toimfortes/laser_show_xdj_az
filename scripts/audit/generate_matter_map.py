import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INCLUDE_PREFIXES = ("src/", "tests/", "scripts/")


def get_file_hash(filepath: Path) -> str:
    """Compute SHA256 hash of file content."""
    sha256_hash = hashlib.sha256()
    with filepath.open("rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def get_repo_head_sha() -> str:
    """Return the current repository HEAD SHA."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def get_file_last_commit_sha(filepath: str) -> str:
    """Get the git SHA of the last commit touching a file."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%H", filepath],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def _extract_decorators(node: ast.AST) -> list[str]:
    decorators: list[str] = []
    if not hasattr(node, "decorator_list"):
        return decorators
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Name):
            decorators.append(decorator.id)
        elif isinstance(decorator, ast.Attribute):
            decorators.append(decorator.attr)
        elif isinstance(decorator, ast.Call):
            if isinstance(decorator.func, ast.Name):
                decorators.append(decorator.func.id)
            elif isinstance(decorator.func, ast.Attribute):
                decorators.append(decorator.func.attr)
    return decorators


def _extract_http_status_code(exc_call: ast.Call) -> int | None:
    for keyword in exc_call.keywords:
        if (
            keyword.arg == "status_code"
            and isinstance(keyword.value, ast.Constant)
            and isinstance(keyword.value.value, int)
        ):
            return keyword.value.value
    if (
        exc_call.args
        and isinstance(exc_call.args[0], ast.Constant)
        and isinstance(exc_call.args[0].value, int)
    ):
        return exc_call.args[0].value
    return None


def parse_file(filepath: Path, relpath: str) -> dict[str, Any]:
    """Parse a Python file into a structured matter map entry."""
    with filepath.open(encoding="utf-8") as f:
        source = f.read()

    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        # Not a Python file or invalid syntax - return basic metadata
        return {
            "line_count": len(source.splitlines()),
            "hash": get_file_hash(filepath),
            "git_sha": get_file_last_commit_sha(relpath),
            "error": "not_python_or_syntax_error",
        }

    functions: dict[str, Any] = {}
    classes: dict[str, Any] = {}
    imports: list[str] = []
    exceptions: list[dict[str, Any]] = []
    patterns: dict[str, list[dict[str, Any]]] = {
        "async_db_calls": [],
        "ownership_predicates": [],
    }

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions[node.name] = {
                "lineno": node.lineno,
                "end_lineno": node.end_lineno,
                "args": [arg.arg for arg in node.args.args],
                "decorators": _extract_decorators(node),
                "is_async": isinstance(node, ast.AsyncFunctionDef),
            }
            continue

        if isinstance(node, ast.ClassDef):
            bases: list[str] = []
            for base in node.bases:
                if isinstance(base, ast.Name):
                    bases.append(base.id)
                elif isinstance(base, ast.Attribute):
                    bases.append(base.attr)
            methods = [
                item.name
                for item in node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            classes[node.name] = {
                "lineno": node.lineno,
                "end_lineno": node.end_lineno,
                "bases": bases,
                "methods": methods,
            }
            continue

        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
            continue

        if isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
            continue

        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            if isinstance(node.exc.func, ast.Name) and node.exc.func.id == "HTTPException":
                exceptions.append(
                    {
                        "type": "HTTPException",
                        "lineno": node.lineno,
                        "status_code": _extract_http_status_code(node.exc),
                    }
                )
            continue

        if (
            isinstance(node, ast.Await)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "execute"
        ):
            patterns["async_db_calls"].append(
                {"lineno": node.lineno, "pattern": "await db.execute(...)"}
            )

    return {
        "line_count": len(source.splitlines()),
        "functions": functions,
        "classes": classes,
        "imports": sorted(set(imports)),
        "exceptions": exceptions,
        "patterns": patterns,
        "hash": get_file_hash(filepath),
        "git_sha": get_file_last_commit_sha(relpath),
    }


def _default_scope_files(include_prefixes: tuple[str, ...]) -> list[str]:
    """Discover tracked Python files for standard code areas."""
    files: list[str] = []
    try:
        tracked = subprocess.run(
            ["git", "ls-files", "--", "*.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "--", "*.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        files = [
            line.strip()
            for line in (tracked.stdout + "\n" + untracked.stdout).splitlines()
            if line.strip()
        ]
    except Exception:
        # Fallback when git is unavailable: walk the repository tree.
        for path in ROOT.rglob("*.py"):
            rel = path.relative_to(ROOT).as_posix()
            files.append(rel)

    filtered = [
        file
        for file in files
        if file.endswith(".py")
        and "__pycache__" not in file
        and any(file.startswith(prefix) for prefix in include_prefixes)
    ]
    return sorted(set(filtered))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate AST-backed matter_map.json for audit scope files."
    )
    parser.add_argument(
        "--output",
        "-o",
        default="-",
        help="Output file path. Defaults to stdout when '-' is used.",
    )
    parser.add_argument(
        "--include-prefix",
        action="append",
        default=[],
        help=(
            "Repo path prefix to include during auto-discovery. Can be repeated. "
            "Defaults to src/, tests/, scripts/."
        ),
    )
    parser.add_argument(
        "files",
        nargs="*",
        help=(
            "Repo-relative files to index. "
            "If omitted, tracked Python files are auto-discovered."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    include_prefixes = tuple(args.include_prefix) if args.include_prefix else DEFAULT_INCLUDE_PREFIXES
    files = args.files if args.files else _default_scope_files(include_prefixes)

    matter_map: dict[str, Any] = {
        "_meta": {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "git_sha": get_repo_head_sha(),
            "scope_files": files,
            "include_prefixes": list(include_prefixes),
        }
    }

    for filepath in files:
        abs_path = ROOT / filepath
        if os.path.exists(abs_path):
            matter_map[filepath] = parse_file(abs_path, filepath)
        else:
            matter_map[filepath] = {"error": "file_not_found"}

    payload = json.dumps(matter_map, indent=2) + "\n"
    if args.output == "-":
        sys.stdout.write(payload)
    else:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = ROOT / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as out_f:
            out_f.write(payload)


if __name__ == "__main__":
    main()
