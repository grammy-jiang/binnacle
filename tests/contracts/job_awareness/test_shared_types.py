"""Runtime shape checks; TYPE-01 runs separately in the locked lint group."""

import ast
import inspect
from pathlib import Path

import pytest

from binnacle.features.commands.job_awareness import models, ports
from tests.contracts.job_awareness.session_import_allowlist import (
    SESSION_LOCAL_FROM_IMPORTS,
    SESSION_MODULES,
)

ROOT = Path(__file__).resolve().parents[3]
LOCAL_PACKAGE = "binnacle.features.commands.job_awareness."
FROZEN_MODULES = {"__init__.py", "identifiers.py", "models.py", "ports.py"}
OPTIONAL_MODULES = SESSION_MODULES | {
    "grants.py",
    "hint_policy.py",
    "hint_render.py",
    "observation.py",
    "projection.py",
    "proofs.py",
    "receipt_schema.py",
    "receipt_store.py",
    "receipts.py",
    "snapshots.py",
}
FROZEN_IMPORTS = {
    "abc",
    "dataclasses",
    "enum",
    "typing",
    "types",
    "re",
    "base64",
    "binascii",
    "hashlib",
}
FROZEN_FROM_IMPORTS = {
    "__future__",
    "abc",
    "dataclasses",
    "enum",
    "typing",
    "types",
    "base64",
    "binascii",
    "hashlib",
}
OPTIONAL_STDLIB_IMPORTS = {
    "asyncio",
    "collections",
    "contextlib",
    "hmac",
    "json",
    "pathlib",
    "secrets",
    "shutil",
    "sqlite3",
    "threading",
}
OPTIONAL_STDLIB_FROM_IMPORTS = {
    "collections": {"OrderedDict"},
    "collections.abc": {
        "AsyncIterator",
        "Awaitable",
        "Callable",
        "Iterator",
        "Mapping",
        "Sequence",
    },
    "contextlib": {"asynccontextmanager", "contextmanager"},
    "pathlib": {"Path"},
    "threading": {"BoundedSemaphore", "Lock", "RLock", "get_ident", "local"},
}
OPTIONAL_LOCAL_FROM_IMPORTS = SESSION_LOCAL_FROM_IMPORTS | {
    "grants.py": {
        "identifiers": {"bounded_int", "canonical_hex"},
        "models": {
            "MAX_INTEGER",
            "AuthorityDecision",
            "BoundaryError",
            "ErrorCode",
            "Failure",
            "GrantVerificationResult",
            "JobRef",
            "PrincipalClaims",
            "Result",
            "RunGrantClaims",
            "Scope",
            "Success",
            "VerifiedPrincipal",
            "VerifiedRunGrant",
        },
        "receipt_schema": {"Limits"},
        "receipt_store": {
            "AuthorityReader",
            "GrantRecord",
            "ReceiptStore",
            "ReceiptTransaction",
            "StoreFailure",
        },
    },
    "hint_policy.py": {
        "identifiers": {"require"},
        "models": {
            "AuthorityDecision",
            "CandidateCategory",
            "ConsumerReceipt",
            "JobRef",
            "Observation",
            "ObservationState",
            "OutputSnapshot",
            "ReceiptState",
            "ReminderCandidate",
            "Scope",
            "Success",
            "TerminalOutcome",
            "VerifiedRunGrant",
        },
        "ports": {"HandleAuthorityPort", "ReceiptQueryPort"},
    },
    "hint_render.py": {
        "models": {
            "CandidateCategory",
            "HintCarrier",
            "JobRef",
            "ReminderCandidate",
            "RenderedHint",
        },
    },
    "observation.py": {
        "models": {
            "AuthorityDecision",
            "ErrorCode",
            "Failure",
            "JobRef",
            "ObservationResult",
            "ObservationState",
            "Scope",
            "Success",
            "VerifiedRunGrant",
        },
        "ports": {"HandleAuthorityPort"},
        "snapshots": {"SnapshotClock", "TrustedCatalog", "failure"},
    },
    "projection.py": {
        "models": {
            "AuthorityDecision",
            "CandidateCategory",
            "ErrorCode",
            "Failure",
            "JobRef",
            "ObservationState",
            "ReceiptState",
            "ReminderCandidate",
            "Result",
            "Scope",
            "Success",
            "VerifiedRunGrant",
        },
        "ports": {"HandleAuthorityPort", "JobObservationPort", "ReceiptQueryPort"},
        "snapshots": {"failure"},
    },
    "proofs.py": {
        "grants": {"DENIED", "SyntheticAuthority"},
        "identifiers": {"bounded_int", "canonical_hex", "snapshot_to_wire"},
        "models": {
            "MAX_SNAPSHOT_BYTES",
            "PAGE_BYTES",
            "AuthorityDecision",
            "BoundaryError",
            "ConsumerReceipt",
            "ErrorCode",
            "Failure",
            "OutputSnapshot",
            "PageEnvelope",
            "PageResult",
            "ReceiptProofRecord",
            "ReceiptQueryResult",
            "Result",
            "RunGrantClaims",
            "Scope",
            "Success",
            "VerifiedRunGrant",
        },
        "ports": {"SnapshotReadPort"},
        "receipt_store": {"ReceiptTransaction", "StoreFailure"},
        "receipts": {"canonical_page"},
    },
    "receipt_schema.py": {
        "identifiers": {"bounded_int", "canonical_hex", "snapshot_from_wire"},
        "models": {
            "MAX_INTEGER",
            "BoundaryError",
            "ByteRange",
            "ErrorCode",
            "Failure",
            "JobRef",
            "OutputSnapshot",
            "PrincipalClaims",
            "ReceiptProofRecord",
            "Result",
            "RunGrantClaims",
            "Scope",
            "Success",
            "VerifiedRunGrant",
        },
    },
    "receipt_store.py": {
        "identifiers": {"canonical_hex", "require", "snapshot_to_wire"},
        "models": {
            "BoundaryError",
            "ConsumerReceipt",
            "ErrorCode",
            "Failure",
            "JobRef",
            "OutputSnapshot",
            "ReceiptProofRecord",
            "ReceiptQueryResult",
            "Result",
            "RunGrantClaims",
            "Scope",
            "VerifiedRunGrant",
        },
        "receipt_schema": {
            "AuthorityReader",
            "GrantRecord",
            "Limits",
            "ReceiptDatabase",
            "Resolver",
            "StoreFailure",
            "abort",
            "decode_proof",
            "deny_resolver",
            "encode",
            "encode_claims",
            "grant_key",
            "snapshot_key",
        },
        "receipts": {"canonical_page", "project_receipt"},
    },
    "receipts.py": {
        "identifiers": {"bounded_int", "require"},
        "models": {
            "MAX_INTEGER",
            "PAGE_BYTES",
            "ByteRange",
            "ConsumerReceipt",
            "OutputSnapshot",
            "ReceiptState",
        },
    },
    "snapshots.py": {
        "models": {
            "MAX_INTEGER",
            "MAX_SNAPSHOT_BYTES",
            "PAGE_BYTES",
            "AuthorityDecision",
            "BoundaryError",
            "ErrorCode",
            "Failure",
            "JobRef",
            "Observation",
            "OutputSnapshot",
            "Result",
            "Scope",
            "Success",
            "VerifiedRunGrant",
        },
        "ports": {"HandleAuthorityPort", "SnapshotLease", "SnapshotLeaseResult"},
    },
}


def _check_portable_imports(tree: ast.AST, filename: str) -> None:
    assert (
        filename in FROZEN_MODULES | OPTIONAL_MODULES
    )  # test contract assertion. # nosec B101
    optional = filename in OPTIONAL_MODULES
    imports = FROZEN_IMPORTS | (OPTIONAL_STDLIB_IMPORTS if optional else set())
    from_imports = FROZEN_FROM_IMPORTS | (
        OPTIONAL_STDLIB_IMPORTS if optional else set()
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert (  # test contract assertion. # nosec B101
                    alias.name in imports
                    if optional
                    else (alias.name.split(".")[0] in imports)
                )
        elif isinstance(node, ast.ImportFrom):
            assert (
                node.level == 0 and node.module is not None
            )  # test contract assertion. # nosec B101
            if optional and node.module.startswith(LOCAL_PACKAGE):
                local_module = node.module.removeprefix(LOCAL_PACKAGE)
                allowed_names = OPTIONAL_LOCAL_FROM_IMPORTS[filename].get(
                    local_module, set()
                )
                assert all(
                    alias.name in allowed_names for alias in node.names
                )  # test contract assertion. # nosec B101
            elif optional and node.module.split(".")[0] in OPTIONAL_STDLIB_IMPORTS:
                allowed_names = OPTIONAL_STDLIB_FROM_IMPORTS.get(node.module, set())
                assert all(
                    alias.name in allowed_names for alias in node.names
                )  # test contract assertion. # nosec B101
            else:
                assert node.module.split(".")[
                    0
                ] in from_imports or (  # test contract assertion. # nosec B101
                    not optional and node.module.startswith(LOCAL_PACKAGE)
                )


def test_shared_ports_are_synchronous_and_read_only():
    assert list(
        inspect.signature(ports.HandleAuthorityPort.check).parameters
    ) == [  # test contract assertion. # nosec B101
        "self",
        "grant",
        "job",
        "required_scopes",
    ]
    for cls, method in [
        (ports.ReceiptQueryPort, "query"),
        (ports.JobObservationPort, "observe"),
        (ports.SnapshotReadPort, "open_verified"),
    ]:
        assert not inspect.iscoroutinefunction(
            getattr(cls, method)
        )  # test contract assertion. # nosec B101
        assert not hasattr(cls, "acknowledge")  # test contract assertion. # nosec B101
    assert {
        v.value for v in models.AuthorityDecision
    } == {  # test contract assertion. # nosec B101
        "authorized",
        "denied",
        "expired",
        "revoked",
    }


def test_inert_portable_modules_and_python310_syntax():
    package = ROOT / "src/binnacle/features/commands/job_awareness"
    assert (
        package / "__init__.py"
    ).read_bytes() == b""  # test contract assertion. # nosec B101
    assert {
        path.name for path in package.glob("*.py")
    } == (  # test contract assertion. # nosec B101
        FROZEN_MODULES | OPTIONAL_MODULES
    )
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(), feature_version=(3, 10))
        _check_portable_imports(tree, path.name)


@pytest.mark.parametrize(
    "source",
    ["import fastmcp", "from binnacle.mcp.callctx import get_call_context"],
)
def test_portable_imports_reject_foreign_modules(source: str):
    with pytest.raises(AssertionError):
        _check_portable_imports(ast.parse(source), "observation.py")


@pytest.mark.parametrize(
    "source",
    [
        "import binnacle.features.commands.job_awareness.platform.linux",
        "from binnacle.features.commands.job_awareness.platform.linux import LinuxProvider",
        "from binnacle.features.commands.job_awareness.receipt_store import ReceiptStore",
        "from binnacle.features.commands.job_awareness.models import ReceiptStore",
    ],
)
def test_portable_imports_reject_local_platform_and_store(source: str):
    with pytest.raises(AssertionError):
        _check_portable_imports(ast.parse(source), "observation.py")


@pytest.mark.parametrize(
    "source",
    [
        "from shutil import os",
        "from shutil import os as operating_system",
        "from pathlib import os",
    ],
)
def test_portable_imports_reject_stdlib_module_reexport(source: str):
    with pytest.raises(AssertionError):
        _check_portable_imports(ast.parse(source), "observation.py")


def test_portable_imports_reject_unknown_filename_and_relative_import():
    with pytest.raises(AssertionError):
        _check_portable_imports(ast.parse("import hashlib"), "unknown.py")
    with pytest.raises(AssertionError):
        _check_portable_imports(
            ast.parse("from .models import JobRef"), "observation.py"
        )


def test_portable_imports_accept_reviewed_names_and_python310_syntax():
    source = (
        "from collections.abc import Callable\n"
        "from binnacle.features.commands.job_awareness.models import JobRef\n"
        "from binnacle.features.commands.job_awareness.snapshots import failure\n"
    )
    _check_portable_imports(
        ast.parse(source, feature_version=(3, 10)), "observation.py"
    )
    with pytest.raises(SyntaxError):
        ast.parse("type Alias = int", feature_version=(3, 10))


def test_private_serialization_matches_committed_schemas():
    import json

    from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

    from binnacle.features.commands.job_awareness.identifiers import (
        job_ref_from_wire,
        job_ref_to_wire,
        receipt_from_wire,
        receipt_result_from_wire,
        receipt_result_to_wire,
        receipt_to_wire,
        snapshot_from_wire,
        snapshot_to_wire,
    )

    folder = ROOT / "docs/job-awareness-implementation/p0/contract-schemas"
    schema = json.loads((folder / "contracts.schema.json").read_text())
    examples = json.loads((folder / "examples.json").read_text())
    converters = {
        "JobRef": (job_ref_from_wire, job_ref_to_wire),
        "OutputSnapshot": (snapshot_from_wire, snapshot_to_wire),
        "ConsumerReceipt": (receipt_from_wire, receipt_to_wire),
        "ReceiptQueryResult": (receipt_result_from_wire, receipt_result_to_wire),
    }
    for row in examples["valid"]:
        if row["type"] in converters:
            parse, serialize = converters[row["type"]]
            wire = serialize(parse(row["value"]))
            assert wire == row["value"]  # test contract assertion. # nosec B101
            Draft202012Validator(
                {"$ref": "#/$defs/" + row["type"], "$defs": schema["$defs"]}
            ).validate(wire)
    import pytest

    for row in examples["invalid"]:
        if row["type"] in converters:
            with pytest.raises(ValueError):
                converters[row["type"]][0](row["value"])
