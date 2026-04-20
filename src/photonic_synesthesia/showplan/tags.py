"""Section tag generation + query helpers.

Per Task 2 Step 6 of the professional-lighting rollout plan. Tags emit
the role/lead/venue triple plus a laser-on/off boolean tag — enough
for the operator workspace's tag bank to filter by intent.
"""

from __future__ import annotations


def build_section_tags(
    *,
    section_role: str,
    lead_family: str,
    venue_mode: str,
    laser_enabled: bool,
) -> list[str]:
    """Return a stable list of tags for a section."""
    return [
        f"role:{section_role}",
        f"lead:{lead_family}",
        f"venue:{venue_mode}",
        "laser:on" if laser_enabled else "laser:off",
    ]
