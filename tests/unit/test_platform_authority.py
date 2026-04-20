from photonic_synesthesia.platform import ControlAuthorityService, LeaseAcquireRequest, OperatorRole


def test_control_authority_grants_single_operator_lease() -> None:
    authority = ControlAuthorityService()

    response = authority.acquire(
        LeaseAcquireRequest(
            issuer_id="alice",
            session_id="client-suggested-sess-1",
            role=OperatorRole.OPERATOR,
            ttl_seconds=300,
        )
    )

    assert response.granted is True
    assert response.lease is not None
    # Cycle-5 CRITICAL (SECURE): server MINTS session_id rather than
    # trusting the client's. Assert it's an opaque server-generated
    # token (not the client's suggestion) with enough entropy.
    assert response.lease.session_id != "client-suggested-sess-1"
    assert len(response.lease.session_id) >= 32  # secrets.token_urlsafe(32) yields >= 43 chars


def test_control_authority_rejects_second_lease_without_force() -> None:
    authority = ControlAuthorityService()
    first = authority.acquire(
        LeaseAcquireRequest(
            issuer_id="alice",
            session_id="client-sess-1",
            role=OperatorRole.OPERATOR,
            ttl_seconds=300,
        )
    )
    assert first.granted is True
    held_session_id = first.lease.session_id  # server-minted

    response = authority.acquire(
        LeaseAcquireRequest(
            issuer_id="bob",
            session_id="client-sess-2",
            role=OperatorRole.OPERATOR,
            ttl_seconds=300,
        )
    )

    assert response.granted is False
    assert response.lease is not None
    # Existing lease still held; its session_id is the server-minted
    # value from the first acquire, NOT any client-supplied string.
    assert response.lease.session_id == held_session_id


def test_control_authority_force_takeover_refused_when_env_var_unset(monkeypatch) -> None:
    """Cycle-5 CRITICAL (SECURE): force-takeover requires
    PHOTONIC_FORCE_TAKEOVER_TOKEN env var. When unset, even a caller
    passing `force=True` AND a matching-looking token is refused."""
    monkeypatch.delenv("PHOTONIC_FORCE_TAKEOVER_TOKEN", raising=False)
    authority = ControlAuthorityService()
    first = authority.acquire(
        LeaseAcquireRequest(
            issuer_id="alice",
            session_id="c1",
            role=OperatorRole.OPERATOR,
            ttl_seconds=300,
        )
    )
    assert first.granted is True

    # Bob tries to force-takeover with a guessed token.
    response = authority.acquire(
        LeaseAcquireRequest(
            issuer_id="bob",
            session_id="c2",
            role=OperatorRole.OPERATOR,
            ttl_seconds=300,
            force=True,
        ),
        force_token="anything",
    )
    assert response.granted is False
    assert "env var is not set" in response.message


def test_control_authority_force_takeover_allowed_with_valid_token(monkeypatch) -> None:
    """Cycle-5 CRITICAL (SECURE): when the env var IS set and the
    caller supplies a matching X-Force-Takeover-Token, force-takeover
    is allowed."""
    monkeypatch.setenv("PHOTONIC_FORCE_TAKEOVER_TOKEN", "secret-admin-token")
    authority = ControlAuthorityService()
    first = authority.acquire(
        LeaseAcquireRequest(
            issuer_id="alice",
            session_id="c1",
            role=OperatorRole.OPERATOR,
            ttl_seconds=300,
        )
    )
    assert first.granted is True
    first_session = first.lease.session_id

    response = authority.acquire(
        LeaseAcquireRequest(
            issuer_id="bob",
            session_id="c2",
            role=OperatorRole.OPERATOR,
            ttl_seconds=300,
            force=True,
        ),
        force_token="secret-admin-token",
    )
    assert response.granted is True
    # Server minted a NEW session_id for the new lease — it's not Bob's
    # suggestion AND it's not Alice's.
    assert response.lease.session_id != "c2"
    assert response.lease.session_id != first_session


def test_control_authority_force_takeover_refused_with_wrong_token(monkeypatch) -> None:
    """Cycle-5 CRITICAL (SECURE): wrong force token is refused even
    when the env var is set. Uses `secrets.compare_digest` under the
    hood so timing attacks are mitigated."""
    monkeypatch.setenv("PHOTONIC_FORCE_TAKEOVER_TOKEN", "real-admin-token")
    authority = ControlAuthorityService()
    authority.acquire(
        LeaseAcquireRequest(
            issuer_id="alice",
            session_id="c1",
            role=OperatorRole.OPERATOR,
            ttl_seconds=300,
        )
    )
    response = authority.acquire(
        LeaseAcquireRequest(
            issuer_id="bob",
            session_id="c2",
            role=OperatorRole.OPERATOR,
            ttl_seconds=300,
            force=True,
        ),
        force_token="wrong-token",
    )
    assert response.granted is False
    assert "invalid X-Force-Takeover-Token" in response.message
