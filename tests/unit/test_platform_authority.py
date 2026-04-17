from photonic_synesthesia.platform import ControlAuthorityService, LeaseAcquireRequest, OperatorRole


def test_control_authority_grants_single_operator_lease() -> None:
    authority = ControlAuthorityService()

    response = authority.acquire(
        LeaseAcquireRequest(
            issuer_id="alice",
            session_id="sess-1",
            role=OperatorRole.OPERATOR,
            ttl_seconds=300,
        )
    )

    assert response.granted is True
    assert response.lease is not None
    assert response.lease.session_id == "sess-1"


def test_control_authority_rejects_second_lease_without_force() -> None:
    authority = ControlAuthorityService()
    authority.acquire(
        LeaseAcquireRequest(
            issuer_id="alice",
            session_id="sess-1",
            role=OperatorRole.OPERATOR,
            ttl_seconds=300,
        )
    )

    response = authority.acquire(
        LeaseAcquireRequest(
            issuer_id="bob",
            session_id="sess-2",
            role=OperatorRole.OPERATOR,
            ttl_seconds=300,
        )
    )

    assert response.granted is False
    assert response.lease is not None
    assert response.lease.session_id == "sess-1"
