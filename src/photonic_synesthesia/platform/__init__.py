"""Platform-level contracts and lightweight control-plane services."""

from photonic_synesthesia.platform.authority import ControlAuthorityService
from photonic_synesthesia.platform.clock import PlatformClock, SystemClock
from photonic_synesthesia.platform.commands import CommandReceipt, InMemoryCommandBus
from photonic_synesthesia.platform.contracts import (
    CommandType,
    ControlLease,
    DirectorSummary,
    ExecutionSnapshot,
    LeaseAcquireRequest,
    LeaseAcquireResponse,
    LiveHealth,
    OperatorCommand,
    OperatorRole,
    PlatformEvent,
    PlatformEventType,
    SafetySummary,
    SemanticFrame,
)
from photonic_synesthesia.platform.events import InMemoryEventBus
from photonic_synesthesia.platform.runtime_context import (
    clear_shared_control_plane_service,
    get_shared_control_plane_service,
    set_shared_control_plane_service,
)
from photonic_synesthesia.platform.state_service import ControlPlaneStateService

__all__ = [
    "CommandReceipt",
    "CommandType",
    "ControlAuthorityService",
    "ControlPlaneStateService",
    "ControlLease",
    "DirectorSummary",
    "ExecutionSnapshot",
    "InMemoryCommandBus",
    "InMemoryEventBus",
    "LeaseAcquireRequest",
    "LeaseAcquireResponse",
    "LiveHealth",
    "OperatorCommand",
    "OperatorRole",
    "PlatformClock",
    "PlatformEvent",
    "PlatformEventType",
    "SafetySummary",
    "SemanticFrame",
    "SystemClock",
    "clear_shared_control_plane_service",
    "get_shared_control_plane_service",
    "set_shared_control_plane_service",
]
