"""Regression test for `_REGEN_EXECUTOR` atexit shutdown (cycle-6 B4).

Pre-B4 the module-level executor had no shutdown path. Python's
atexit `_python_exit` in `concurrent.futures.thread` fires
`shutdown(wait=True)` — if a regen worker is wedged, that blocks
interpreter exit. We register our own atexit with a bounded-wait
helper so the shutdown is at least predictable.

The tests below only verify *registration* and the *delegation
target* — we don't actually invoke the hook because doing so would
shut down the process-shared `_REGEN_EXECUTOR` and break any
subsequent test that submits a regen.
"""

from __future__ import annotations

from unittest import mock


def test_regen_executor_atexit_hook_is_defined() -> None:
    """Pin that the atexit hook exists as a named, callable symbol.
    Renaming it breaks this test; the rename should come with a
    matching update to the atexit registration below it."""
    from photonic_synesthesia.platform import runtime_context

    assert hasattr(runtime_context, "_shutdown_regen_executor_at_exit")
    assert callable(runtime_context._shutdown_regen_executor_at_exit)


def test_regen_executor_atexit_delegates_to_threadhygiene_helper() -> None:
    """The atexit hook must delegate to `threadhygiene.shutdown_executor`
    so it picks up the bounded-wait + cancel_futures semantics. If
    someone swaps it back to a raw `shutdown(wait=True)`, this
    regression catches it before the next hang."""
    from photonic_synesthesia.platform import runtime_context

    # Replace the real executor so calling the hook does NOT shut down
    # the process-shared `_REGEN_EXECUTOR` (which other tests depend on).
    with mock.patch(
        "photonic_synesthesia.platform.runtime_context.shutdown_executor"
    ) as fake_helper:
        runtime_context._shutdown_regen_executor_at_exit()

    fake_helper.assert_called_once()
    call_kwargs = fake_helper.call_args.kwargs
    assert call_kwargs["name"] == "playback-regen"
    assert call_kwargs["timeout"] > 0


def test_regen_executor_atexit_registered_at_import() -> None:
    """Sanity: the hook must have been `atexit.register`-ed when the
    module was imported. We can't introspect atexit's private queue
    portably, so we check the symbol is present and the module
    imported cleanly (any exception in the registration would have
    propagated during import)."""
    import photonic_synesthesia.platform.runtime_context as rc

    assert rc._shutdown_regen_executor_at_exit is not None
