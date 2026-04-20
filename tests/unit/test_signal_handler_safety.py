"""Regression tests for E1: signal-handler async-safety (cycle-6 C1+C2).

Pins:
  - CLI SIGINT/SIGTERM handler flips `graph._running` ONLY, not `graph.stop()`.
  - SIGUSR1 handler uses `os.write` (async-signal-safe), not
    `logger.warning`, and prefers `request_blackout` (flag-set) over
    `emergency_blackout` (does socket IO).
"""

from __future__ import annotations

import signal
from unittest import mock


def test_cli_run_shutdown_handler_flips_running_flag_only() -> None:
    """Core C1 invariant: the signal handler must NOT call graph.stop()
    inline. If it did, teardown would run in signal context where
    lock re-acquisition is unsafe (the incident class B6 introduced
    locks for)."""
    import ast
    import inspect
    from photonic_synesthesia.ui import cli

    source = inspect.getsource(cli)
    tree = ast.parse(source)

    shutdown_fns: list[ast.FunctionDef] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_shutdown":
            shutdown_fns.append(node)

    assert len(shutdown_fns) >= 2, (
        f"expected >=2 _shutdown handlers (run + run-file); got {len(shutdown_fns)}"
    )

    for fn in shutdown_fns:
        # Collect all `Attribute` assignments + all `Call` nodes inside.
        calls: list[str] = []
        assigns: list[str] = []
        for sub in ast.walk(fn):
            if isinstance(sub, ast.Call):
                calls.append(ast.unparse(sub))
            elif isinstance(sub, ast.Assign):
                assigns.append(ast.unparse(sub))

        # Must flip graph._running = False
        assert any("graph._running" in a and "False" in a for a in assigns), (
            f"_shutdown at line {fn.lineno} must assign graph._running = False; "
            f"assigns were: {assigns}"
        )
        # Must NOT call graph.stop()
        bad = [c for c in calls if c == "graph.stop()"]
        assert not bad, (
            f"_shutdown at line {fn.lineno} must NOT call graph.stop() inline; "
            f"found: {bad}"
        )


def test_sigusr1_handler_uses_os_write_not_logger() -> None:
    """Core C2 invariant: the SIGUSR1 handler runs in async signal
    context. `logger.warning` acquires structlog's internal lock.
    If the signal lands while main holds that lock, handler
    deadlocks trying to re-acquire. Must use `os.write` instead."""
    import inspect
    from photonic_synesthesia.graph import builder

    source = inspect.getsource(builder)
    # Extract the _on_sigusr1 body.
    marker = "def _on_sigusr1("
    assert marker in source
    start = source.index(marker)
    # Extract until the next dedent after the handler body.
    body_end = source.index("\n        # Cycle-6 B5:", start)
    handler_body = source[start:body_end]

    assert "os.write" in handler_body, (
        "SIGUSR1 handler MUST use os.write (async-signal-safe), not logger"
    )
    assert "logger.warning" not in handler_body, (
        "SIGUSR1 handler MUST NOT call logger.warning (acquires internal lock)"
    )
    assert "logger.exception" not in handler_body, (
        "SIGUSR1 handler MUST NOT call logger.exception (acquires internal lock)"
    )


def test_sigusr1_handler_prefers_request_blackout_over_emergency_blackout() -> None:
    """Core C2 invariant: `emergency_blackout` on ILDADACOutputNode
    does socket IO to the Ether Dream DAC — not safe to do from
    signal context, even if the RLock is reentrant. Prefer
    `request_blackout` which only flips a flag; the ILDA
    emergency_loop polls the flag and does the actuation from
    normal thread context."""
    import inspect
    from photonic_synesthesia.graph import builder

    source = inspect.getsource(builder)
    marker = "def _on_sigusr1("
    start = source.index(marker)
    body_end = source.index("\n        # Cycle-6 B5:", start)
    handler_body = source[start:body_end]

    # The getattr chain must list request_blackout BEFORE emergency_blackout.
    req_idx = handler_body.find("request_blackout")
    emerg_idx = handler_body.find("emergency_blackout")
    assert req_idx > 0
    assert emerg_idx > 0
    assert req_idx < emerg_idx, (
        f"request_blackout must appear before emergency_blackout in the "
        f"getattr chain (preference order); got request @ {req_idx}, "
        f"emergency @ {emerg_idx}"
    )


def test_cli_shutdown_handler_matches_signal_handler_signature() -> None:
    """Defensive: `signal.signal(SIG, handler)` requires handler(signum, frame).
    If a refactor changed the arity, this test surfaces it immediately."""
    from photonic_synesthesia.ui import cli

    # Invoke the closure inside the `run` command via exec is too
    # intrusive; instead, just check the source has the right sig.
    import inspect
    source = inspect.getsource(cli)
    assert "def _shutdown(signum: int, frame: object) -> None:" in source
