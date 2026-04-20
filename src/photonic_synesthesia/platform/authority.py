"""Control lease authority service for the web control plane."""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from threading import Lock

from photonic_synesthesia.platform.contracts import (
    ControlLease,
    LeaseAcquireRequest,
    LeaseAcquireResponse,
    OperatorRole,
)


# Cycle-5 CRITICAL (SECURE): force-takeover is a privileged operation
# that must NOT be available to any local caller. Gated by an env var
# token. When unset, force-takeover is refused in all cases.
_FORCE_TOKEN_ENV_VAR = "PHOTONIC_FORCE_TAKEOVER_TOKEN"


class ControlAuthorityService:
    """Owns the single active live-control lease.

    Cycle-5 CRITICAL (SECURE) hardening:

    1. **Server-minted session IDs.** The lease session_id is generated
       via `secrets.token_urlsafe(32)` on every acquire. Callers cannot
       forge their own — any `session_id` in `LeaseAcquireRequest` is
       IGNORED. This closes the attack where a local process minted a
       client-side `session_id`, called `acquire`, then called
       `/api/control/arm` with the same `session_id`.

    2. **Force-takeover gated by env-var token.** `request.force=True`
       now requires `X-Force-Takeover-Token` matching
       `PHOTONIC_FORCE_TAKEOVER_TOKEN` environment variable. If the
       env var is unset OR the header is missing/mismatched, force
       takeover is refused. The header is passed via a separate
       `acquire_with_force_token()` call; the base `acquire()` refuses
       `force=True` outright.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._lease: ControlLease | None = None

    def get_active_lease(self) -> ControlLease | None:
        with self._lock:
            self._expire_if_needed()
            return self._lease.model_copy(deep=True) if self._lease else None

    def acquire(
        self,
        request: LeaseAcquireRequest,
        force_token: str | None = None,
    ) -> LeaseAcquireResponse:
        """Acquire the control lease. See class docstring for auth model.

        `force_token` is the X-Force-Takeover-Token header value. If
        `request.force=True` is set without a valid token, takeover is
        refused. If `force=False`, `force_token` is ignored.
        """
        with self._lock:
            self._expire_if_needed()
            if self._lease and request.force:
                # Cycle-5 CRITICAL: force-takeover requires env-var token.
                expected = os.environ.get(_FORCE_TOKEN_ENV_VAR)
                if not expected:
                    return LeaseAcquireResponse(
                        granted=False,
                        lease=self._lease.model_copy(deep=True),
                        message=(
                            "Force-takeover refused: "
                            f"{_FORCE_TOKEN_ENV_VAR} env var is not set on the server."
                        ),
                    )
                if not force_token or not secrets.compare_digest(force_token, expected):
                    return LeaseAcquireResponse(
                        granted=False,
                        lease=self._lease.model_copy(deep=True),
                        message="Force-takeover refused: invalid X-Force-Takeover-Token.",
                    )
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

            expires_at = datetime.now(timezone.utc) + timedelta(seconds=request.ttl_seconds)
            # Cycle-5 CRITICAL: server MINTS session_id. Ignore whatever
            # the caller put in `request.session_id` — it's untrusted
            # input. The caller gets the server-minted ID back in the
            # response and must use it for subsequent `require_control`
            # calls.
            server_session_id = secrets.token_urlsafe(32)
            self._lease = ControlLease(
                issuer_id=request.issuer_id,
                session_id=server_session_id,
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
        if self._lease and self._lease.expires_at <= datetime.now(timezone.utc):
            self._lease = None
