"""Safe console entrypoint target for the optional web interface."""

from __future__ import annotations

import sys


def main() -> None:
    """Fail fast with a clear message until the web panel is implemented."""
    sys.stderr.write(
        "photonic-web entrypoint is available, but the web panel is not implemented yet.\n"
    )
    raise SystemExit(1)
