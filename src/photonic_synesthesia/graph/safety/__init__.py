"""Safety-critical helpers shared across the graph pipeline.

Cycle-5 panel LS2 redesign: predicates that MUST return identical results
across multiple nodes (so those nodes can't disagree on whether a point
is in a protected zone) live here as a single source of truth.
"""

from photonic_synesthesia.graph.safety.protected_zone import (
    ProtectedHalfPlane,
    is_point_protected,
    protected_half_plane_for_fixture,
    validate_laser_zone_config,
)

__all__ = [
    "ProtectedHalfPlane",
    "is_point_protected",
    "protected_half_plane_for_fixture",
    "validate_laser_zone_config",
]
