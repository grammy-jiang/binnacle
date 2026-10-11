"""Strict bounded private-record boundaries. No normalization or source I/O.

Only the explicitly named data parsers exist. None deserializes opaque handles.
All validation errors use fixed text and never echo a selector or credential.
"""

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.features.commands.job_awareness.models import (
        ConsumerReceipt,
        JobRef,
        OutputSnapshot,
        ReceiptQueryResult,
        Result,
        Scope,
        VerifiedRunGrant,
    )
    from binnacle.features.commands.job_awareness.ports import HandleAuthorityPort


def require(condition: bool) -> None:
    if not condition:
        raise ValueError("Invalid private record")


def canonical_hex(value: object, digits: int, prefix: str = "") -> str:
    require(type(value) is str)
    if not isinstance(value, str):
        raise ValueError("Invalid private record")  # noqa: TRY004 - uniform boundary
    require(len(value) == len(prefix) + digits)
    require(
        value.startswith(prefix)
        and re.fullmatch("[0-9a-f]{" + str(digits) + "}", value[len(prefix) :])
        is not None
    )
    return value


def bounded_int(value: object, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("Invalid private record")
    return value


def _record(raw: object, keys: tuple[str, ...]) -> dict[str, object]:
    # Check cardinality before touching keys or values, including oversized input.
    if type(raw) is not dict or len(raw) != len(keys):
        raise ValueError("Invalid private record")
    require(all(type(key) is str and key in keys for key in raw))
    return {key: raw[key] for key in keys}


def _text(raw: object, maximum: int = 64) -> str:
    if type(raw) is not str or len(raw) > maximum:
        raise ValueError("Invalid private record")
    return raw


def job_ref_from_wire(raw: object) -> "JobRef":
    from binnacle.features.commands.job_awareness.models import JobRef

    obj = _record(raw, ("run_namespace", "job_id", "incarnation"))
    return JobRef(
        canonical_hex(obj["run_namespace"], 32, "ja1_"),
        canonical_hex(obj["job_id"], 12),
        canonical_hex(obj["incarnation"], 32, "g1_"),
    )


def job_ref_to_wire(job: "JobRef") -> dict[str, object]:
    return {
        "run_namespace": job.run_namespace,
        "job_id": job.job_id,
        "incarnation": job.incarnation,
    }


def admit_job_ref(
    raw: object,
    grant: "VerifiedRunGrant",
    authority: "HandleAuthorityPort",
    required_scopes: "frozenset[Scope]",
) -> "Result[JobRef]":
    """Parse then revalidate injected authority; no backend or discovery access."""
    from binnacle.features.commands.job_awareness.models import (
        AuthorityDecision,
        BoundaryError,
        ErrorCode,
        Failure,
        Success,
    )

    denied = Failure(BoundaryError(ErrorCode.DENIED))
    try:
        job = job_ref_from_wire(raw)
    except ValueError:
        return denied
    if authority.check(grant, job, required_scopes) is not AuthorityDecision.AUTHORIZED:
        return denied
    return Success(job)


def snapshot_to_wire(snapshot: "OutputSnapshot") -> dict[str, object]:
    return {
        "job": job_ref_to_wire(snapshot.job),
        "sha256": snapshot.sha256,
        "byte_length": snapshot.byte_length,
        "terminal": {
            "kind": snapshot.terminal.kind.value,
            "value": snapshot.terminal.value,
        },
        "sealed_at_ms": snapshot.sealed_at_ms,
        "retained_until_ms": snapshot.retained_until_ms,
        "source_kind": snapshot.source_kind.value,
        "seal_id": snapshot.seal_id,
    }


def snapshot_from_wire(raw: object) -> "OutputSnapshot":
    from binnacle.features.commands.job_awareness.models import (
        MAX_INTEGER,
        MAX_SNAPSHOT_BYTES,
        OutputSnapshot,
        SourceKind,
        TerminalKind,
        TerminalOutcome,
    )

    obj = _record(
        raw,
        (
            "job",
            "sha256",
            "byte_length",
            "terminal",
            "sealed_at_ms",
            "retained_until_ms",
            "source_kind",
            "seal_id",
        ),
    )
    terminal = _record(obj["terminal"], ("kind", "value"))
    try:
        kind = TerminalKind(_text(terminal["kind"]))
        source = SourceKind(_text(obj["source_kind"]))
    except ValueError:
        raise ValueError("Invalid private record") from None
    return OutputSnapshot(
        job_ref_from_wire(obj["job"]),
        canonical_hex(obj["sha256"], 64),
        bounded_int(obj["byte_length"], 0, MAX_SNAPSHOT_BYTES),
        TerminalOutcome(kind, bounded_int(terminal["value"], 0, 255)),
        bounded_int(obj["sealed_at_ms"], 0, MAX_INTEGER),
        bounded_int(obj["retained_until_ms"], 0, MAX_INTEGER),
        source,
        canonical_hex(obj["seal_id"], 32),
    )


def receipt_to_wire(receipt: "ConsumerReceipt") -> dict[str, object]:
    return {
        "state": receipt.state.value,
        "job": job_ref_to_wire(receipt.job),
        "snapshot_sha256": receipt.snapshot_sha256,
        "ranges": [{"start": item.start, "stop": item.stop} for item in receipt.ranges],
        "empty_confirmed": receipt.empty_confirmed,
        "commit_version": receipt.commit_version,
        "authority_revision": receipt.authority_revision,
    }


def receipt_from_wire(raw: object) -> "ConsumerReceipt":
    from binnacle.features.commands.job_awareness.models import (
        MAX_INTEGER,
        MAX_SNAPSHOT_BYTES,
        ByteRange,
        ConsumerReceipt,
        ReceiptState,
    )

    obj = _record(
        raw,
        (
            "state",
            "job",
            "snapshot_sha256",
            "ranges",
            "empty_confirmed",
            "commit_version",
            "authority_revision",
        ),
    )
    ranges = obj["ranges"]
    if type(ranges) is not list or len(ranges) > 64:
        raise ValueError("Invalid private record")
    parsed = []
    for raw_range in ranges:
        item = _record(raw_range, ("start", "stop"))
        parsed.append(
            ByteRange(
                bounded_int(item["start"], 0, MAX_SNAPSHOT_BYTES),
                bounded_int(item["stop"], 0, MAX_SNAPSHOT_BYTES),
            )
        )
    empty = obj["empty_confirmed"]
    if type(empty) is not bool:
        raise ValueError("Invalid private record")
    try:
        state = ReceiptState(_text(obj["state"]))
    except ValueError:
        raise ValueError("Invalid private record") from None
    return ConsumerReceipt(
        state,
        job_ref_from_wire(obj["job"]),
        canonical_hex(obj["snapshot_sha256"], 64),
        tuple(parsed),
        empty,
        bounded_int(obj["commit_version"], 0, MAX_INTEGER),
        bounded_int(obj["authority_revision"], 1, MAX_INTEGER),
    )


def receipt_result_to_wire(result: "ReceiptQueryResult") -> dict[str, object]:
    from binnacle.features.commands.job_awareness.models import Failure

    if isinstance(result, Failure):
        return {"ok": False, "error": {"code": result.error.code.value}}
    return {"ok": True, "receipt": receipt_to_wire(result.value)}


def receipt_result_from_wire(raw: object) -> "ReceiptQueryResult":
    from binnacle.features.commands.job_awareness.models import (
        BoundaryError,
        ErrorCode,
        Failure,
        Success,
    )

    if type(raw) is not dict or len(raw) != 2:
        raise ValueError("Invalid private record")
    if raw.get("ok") is True:
        return Success(receipt_from_wire(_record(raw, ("ok", "receipt"))["receipt"]))
    require(raw.get("ok") is False)
    obj = _record(raw, ("ok", "error"))
    error = _record(obj["error"], ("code",))
    try:
        code = ErrorCode(_text(error["code"]))
    except ValueError:
        raise ValueError("Invalid private record") from None
    return Failure(BoundaryError(code))
