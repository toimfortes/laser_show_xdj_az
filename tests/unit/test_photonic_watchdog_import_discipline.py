"""Guard rail: `photonic_watchdog/` must remain stdlib-only.

Cycle-5 panel LS3: the watchdog runs in a `multiprocessing.Process`
launched with `start_method='spawn'`. Spawn re-executes this module's
import chain in the child; pulling in `photonic_synesthesia.*` (librosa,
numpy, madmom) would add seconds of startup AND reintroduce the
GIL-holding-C-extension scenario the watchdog exists to detect.

This test parses every `.py` file under `photonic_watchdog/` and fails
if any of them contain an `import photonic_synesthesia...` or
`from photonic_synesthesia... import ...`. AST parse — not `importlib`
— so this check works without actually importing and cannot be defeated
by lazy-imports inside functions.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


def _watchdog_python_files() -> list[Path]:
    root = Path(__file__).resolve().parents[2] / "photonic_watchdog"
    assert root.is_dir(), f"expected photonic_watchdog at {root}"
    return sorted(root.rglob("*.py"))


@pytest.mark.parametrize("file_path", _watchdog_python_files())
def test_watchdog_file_does_not_import_photonic_synesthesia(
    file_path: Path,
) -> None:
    """Every file in photonic_watchdog/ MUST stay stdlib-only (plus its
    own intra-package imports). See the module docstring for why."""
    source = file_path.read_text()
    tree = ast.parse(source, filename=str(file_path))

    banned_module_prefix = "photonic_synesthesia"
    offenders: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(banned_module_prefix):
                    offenders.append(
                        f"import {alias.name} at line {node.lineno}"
                    )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith(banned_module_prefix):
                offenders.append(
                    f"from {module} import ... at line {node.lineno}"
                )

    assert not offenders, (
        f"{file_path.relative_to(file_path.parents[2])} imports photonic_synesthesia "
        f"(spawn would reload librosa/numpy/madmom in the watchdog child):\n  "
        + "\n  ".join(offenders)
    )


def test_watchdog_package_has_at_least_the_expected_files() -> None:
    """Sanity: prevent a future refactor that accidentally empties the
    watchdog package from turning the parametrized test above into a
    silent no-op."""
    paths = {p.name for p in _watchdog_python_files()}
    assert "__init__.py" in paths
    assert "shmem.py" in paths
    assert "loop.py" in paths
