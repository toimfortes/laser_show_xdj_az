"""Regression tests for the module-global regen executor exit behavior."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path


def test_regen_executor_shutdown_path_does_not_hang_process_exit() -> None:
    """A wedged regen worker must not pin interpreter exit after our
    bounded shutdown hook runs."""
    root = Path(__file__).resolve().parents[2]
    script = textwrap.dedent(
        f"""
        import sys
        import threading
        sys.path.insert(0, {str(root / "src")!r})
        from photonic_synesthesia.platform.runtime_context import (
            _REGEN_EXECUTOR,
            _shutdown_regen_executor_at_exit,
        )

        stop = threading.Event()
        _REGEN_EXECUTOR.submit(stop.wait)
        _shutdown_regen_executor_at_exit()
        print("exiting")
        """
    )

    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=6.0,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "exiting" in completed.stdout
