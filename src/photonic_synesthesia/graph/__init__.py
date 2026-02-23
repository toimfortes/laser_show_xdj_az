"""LangGraph orchestration for Photonic Synesthesia."""

from __future__ import annotations

from typing import Any


def build_photonic_graph(*args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
    """Lazy import to avoid heavy runtime deps during light module imports."""
    from photonic_synesthesia.graph.builder import build_photonic_graph as _build

    return _build(*args, **kwargs)


def build_minimal_graph(*args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
    """Lazy import to avoid heavy runtime deps during light module imports."""
    from photonic_synesthesia.graph.builder import build_minimal_graph as _build

    return _build(*args, **kwargs)


def __getattr__(name: str) -> Any:
    if name == "PhotonicGraph":
        from photonic_synesthesia.graph.builder import PhotonicGraph

        return PhotonicGraph
    raise AttributeError(name)


__all__ = ["build_photonic_graph", "build_minimal_graph", "PhotonicGraph"]
