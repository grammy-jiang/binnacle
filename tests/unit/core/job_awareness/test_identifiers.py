"""Canonical selectors must fail before any consumer source access."""

import pytest

from binnacle.features.commands.job_awareness.identifiers import (
    admit_job_ref,
    job_ref_from_wire,
    job_ref_to_wire,
)
from binnacle.features.commands.job_awareness.models import (
    BoundaryError,
    ErrorCode,
    Failure,
    JobRef,
    Scope,
    Success,
)
from tests.contracts.job_awareness.fakes import FakeHandleAuthority

VALID = {
    "run_namespace": "ja1_" + "1" * 32,
    "job_id": "abcdef012345",
    "incarnation": "g1_" + "2" * 32,
}


@pytest.mark.parametrize(
    "bad",
    [
        "/etc/passwd",
        "..",
        ".",
        "a/b",
        "a\\b",
        "a:b",
        "\x00",
        "\r",
        "\n",
        "\x7f",
        "%2e%2e",
        "ａｂｃｄｅｆ012345",
        "ABCDEF012345",
        "a" * 100000,
        "",
        True,
        1,
        None,
    ],
    ids=[
        "absolute",
        "dotdot",
        "dot",
        "slash",
        "backslash",
        "colon",
        "nul",
        "cr",
        "lf",
        "del",
        "percent",
        "unicode",
        "uppercase",
        "oversize",
        "empty",
        "bool",
        "int",
        "null",
    ],
)
@pytest.mark.parametrize("field", list(VALID))
def test_bad_selector_never_reads_backend(field, bad):
    authority = FakeHandleAuthority()
    grant = authority.issue((job_ref_from_wire(VALID),))
    reads = []
    raw = {**VALID, field: bad}
    result = admit_job_ref(raw, grant, authority, frozenset({Scope.OBSERVE}))
    if isinstance(result, Success):
        reads.append(result.value)
    assert reads == []
    assert result == Failure(BoundaryError(ErrorCode.DENIED))
    assert authority.check_calls == 0
    with pytest.raises(ValueError, match="^Invalid private record$"):
        job_ref_from_wire(raw)


@pytest.mark.parametrize(
    "raw",
    [
        None,
        [],
        "chat-id",
        {**VALID, "chat_id": "trusted"},
        {"job_id": VALID["job_id"]},
        dict.fromkeys(range(1000), "x"),
    ],
)
def test_closed_selector(raw):
    with pytest.raises(ValueError, match="^Invalid private record$"):
        job_ref_from_wire(raw)


@pytest.mark.parametrize(
    "field,value",
    [
        ("run_namespace", "ja1_" + "3" * 32),
        ("incarnation", "g1_" + "4" * 32),
        ("job_id", "123456789abc"),
    ],
)
def test_namespace_and_incarnation_before_backend(field, value):
    authority = FakeHandleAuthority()
    grant = authority.issue((job_ref_from_wire(VALID),))
    reads = []
    result = admit_job_ref(
        {**VALID, field: value}, grant, authority, frozenset({Scope.OBSERVE})
    )
    if isinstance(result, Success):
        reads.append(result.value)
    assert reads == []
    assert result == Failure(BoundaryError(ErrorCode.DENIED))


def test_canonical_identity_roundtrip_and_positive_admission():
    job = JobRef(**VALID)
    assert job_ref_to_wire(job) == VALID
    assert len(job.canonical_key.encode("ascii")) == 85
    authority = FakeHandleAuthority()
    grant = authority.issue((job,))
    assert admit_job_ref(VALID, grant, authority, frozenset({Scope.READ})) == Success(
        job
    )


def test_constructor_also_validates():
    with pytest.raises(ValueError):
        JobRef(VALID["run_namespace"], "../unsafe", VALID["incarnation"])


@pytest.mark.parametrize("state", ["unknown", "expired", "revoked", "epoch"])
def test_all_authority_failures_have_identical_external_denial(state):
    authority = FakeHandleAuthority()
    job = job_ref_from_wire(VALID)
    grant = authority.issue((job,))
    if state == "unknown":
        grant = FakeHandleAuthority().issue((job,))
    elif state == "expired":
        authority.now_ms = authority.claims(grant).expires_at_ms
    elif state == "revoked":
        authority.revoke(grant)
    else:
        authority.rotate_epoch()
    assert admit_job_ref(
        VALID, grant, authority, frozenset({Scope.OBSERVE})
    ) == Failure(BoundaryError(ErrorCode.DENIED))
