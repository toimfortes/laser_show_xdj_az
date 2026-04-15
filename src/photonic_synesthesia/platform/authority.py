"""Control lease authority service for the web control plane."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Lock

from photonic_synesthesia.platform.contracts import (
    ControlLease,
    LeaseAcquireRequest,
    LeaseAcquireResponse,
    OperatorRole,
)


class ControlAuthorityService:
    """Owns the single active live-control lease."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._lease: ControlLease | None = None

    def get_active_lease(self) -> ControlLease | None:
        with self._lock:
            self._expire_if_needed()
            return self._lease.model_copy(deep=True) if self._lease else None

    def acquire(self, request: LeaseAcquireRequest) -> LeaseAcquireResponse:
        with self._lock:
            self._expire_if_needed()
            if self._lease and not request.force:
                return LeaseAcquireResponse(
                    granted=False,
                    lease=self._lease.model_copy(deep=True),
                    message="Control lease is already held",
                )

            role = request.role
            if role not in {OperatorRole.OPERATOR, OperatorRole.ADMIN}:
                return LeaseAcquireResponse(
                    granted=False,
                    lease=self._lease.model_copy(deep=True) if self._lease else None,
                    message="Only operator or admin roles may hold the control lease",
                )

            expires_at = datetime.now(UTC) + timedelta(seconds=request.ttl_seconds)
            self._lease = ControlLease(
                issuer_id=request.issuer_id,
                session_id=request.session_id,
                role=role,
                expires_at=expires_at,
            )
            return LeaseAcquireResponse(
                granted=True,
                lease=self._lease.model_copy(deep=True),
                message="Control lease acquired",
            )

    def release(self, session_id: str, force: bool = False) -> bool:
        with self._lock:
            self._expire_if_needed()
            if self._lease is None:
                return False
            if force or self._lease.session_id == session_id:
                self._lease = None
                return True
            return False

    def has_control(self, session_id: str) -> bool:
        with self._lock:
            self._expire_if_needed()
            return self._lease is not None and self._lease.session_id == session_id

    def _expire_if_needed(self) -> None:
        if self._lease and self._lease.expires_at <= datetime.now(UTC):
            self._lease = None
