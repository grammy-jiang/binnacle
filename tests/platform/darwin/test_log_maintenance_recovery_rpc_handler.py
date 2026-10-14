"""Only one pinned journal can be inspected; no mutations or arbitrary RPC."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from binnacle.platform.darwin import log_maintenance_recovery_rpc as rpc
from binnacle.platform.darwin.log_maintenance_recovery_policy import RecoveryAssessment
from binnacle.platform.darwin.log_maintenance_transaction import (
    MaintenanceTransactionJournal,
)
from tests.platform.darwin.test_log_maintenance_transaction import (
    NONCE,
    advance_to,
    begin,
)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    path = tmp_path / ("txn-" + NONCE)
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    return path


def record(root: Path, phase: str):
    with MaintenanceTransactionJournal(root) as txn:
        report = begin(txn)
        return report if phase == "intent" else advance_to(txn, phase)


def request(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {"version": 1, "op": "inspect", "nonce": NONCE}
    data.update(overrides)
    return data


@pytest.mark.parametrize("phase", rpc._PHASES)
def test_every_valid_phase_yields_only_a_manual_review_report(
    tmp_path: Path, phase: str
) -> None:
    root = tmp_path / ("txn-" + NONCE)
    root.mkdir(mode=0o700)
    value = record(root, phase)
    before = (root / "transaction.json").read_bytes()
    handler = rpc.RecoveryObservationHandler(root)
    reply = handler(request())
    assert reply == rpc._wire(rpc.assess_recovery(value), value.revision)
    assert reply["manual_review_required"] is True
    assert reply["production_authorized"] is False
    assert reply["autonomous_restart_allowed"] is False
    assert (root / "transaction.json").read_bytes() == before
    if phase in {"guardian_armed", "producer_stopped"}:
        assert "producer_may_be_offline" in cast(list[str], reply["risks"])


@pytest.mark.parametrize(
    ("malformed", "match"),
    [
        ({"version": True}, "operation"),
        ({"version": 1.0}, "operation"),
        ({"version": 2}, "operation"),
        ({"version": "1"}, "operation"),
        ({"op": "bootout"}, "operation"),
        ({"op": "bootstrap"}, "operation"),
        ({"op": "kill"}, "operation"),
        ({"op": "prune"}, "operation"),
        ({"op": "restart"}, "operation"),
        ({"op": "inspect\n"}, "operation"),
        ({"op": None}, "operation"),
        ({"nonce": "b" * 32}, "operation"),
        ({"nonce": "a"}, "nonce"),
        ({"nonce": "A" * 32}, "nonce"),
        ({"nonce": 1}, "nonce"),
        ({"nonce": None}, "nonce"),
    ],
)
def test_rpc_request_never_selects_an_operation_other_than_inspection(
    root: Path, malformed: dict[str, object], match: str
) -> None:
    record(root, "guardian_armed")
    handler = rpc.RecoveryObservationHandler(root)
    before = (root / "transaction.json").read_bytes()
    with pytest.raises(rpc.RecoveryRPCRefused, match=match):
        handler(request(**malformed))
    assert (root / "transaction.json").read_bytes() == before


@pytest.mark.parametrize(
    "extra",
    [
        {"path": "/tmp/foreign"},
        {"service": "com.binnacle.mcp"},
        {"command": "rm -rf /"},
        {"credential": "abc"},
        {"timestamp": 123},
        {"peer_pid": os.getpid()},
        {"dry_run": True},
        {"allow_restart": True},
        {"trusted_observations": {}},
    ],
)
def test_untrusted_client_can_never_select_root_service_or_mutation(
    root: Path, extra: dict[str, object]
) -> None:
    record(root, "guardian_armed")
    handler = rpc.RecoveryObservationHandler(root)
    with pytest.raises(rpc.RecoveryRPCRefused, match="operation"):
        handler({**request(), **extra})


@pytest.mark.parametrize("bad", [None, [], (), set(), "inspect", 1])
def test_nonobject_requests_are_rejected(root: Path, bad: object) -> None:
    record(root, "complete")
    with pytest.raises(rpc.RecoveryRPCRefused):
        rpc.RecoveryObservationHandler(root)(cast(dict[str, object], bad))


def test_missing_journal_never_becomes_a_completed_observation(root: Path) -> None:
    handler = rpc.RecoveryObservationHandler(root)
    assert handler(request()) == {
        "version": 1,
        "ok": False,
        "code": "journal_unavailable",
    }
    assert list(root.iterdir()) == []


def test_live_controller_lock_refuses_without_waiting(root: Path) -> None:
    handler = rpc.RecoveryObservationHandler(root)
    with MaintenanceTransactionJournal(root) as txn:
        report = begin(txn)
        assert handler(request()) == {
            "version": 1,
            "ok": False,
            "code": "journal_unavailable",
        }
        assert txn.inspect() == report
    assert handler(request())["ok"] is True


def test_corrupt_record_has_fixed_generic_error_and_does_not_reset(root: Path) -> None:
    record(root, "complete")
    corrupt = b"{not-a-real-journal"
    (root / "transaction.json").write_bytes(corrupt)
    handler = rpc.RecoveryObservationHandler(root)
    assert handler(request()) == {
        "version": 1,
        "ok": False,
        "code": "journal_unavailable",
    }
    assert (root / "transaction.json").read_bytes() == corrupt


@pytest.mark.parametrize(
    "badname",
    [
        "nope",
        "txn-abc",
        "txn-" + "A" * 32,
        "txn-" + "g" * 32,
        "transaction-" + NONCE,
    ],
)
def test_foreign_root_is_refused_before_any_file_access(
    tmp_path: Path, badname: str
) -> None:
    foreign = tmp_path / badname
    with pytest.raises(rpc.RecoveryRPCRefused, match="root not pinned"):
        rpc.RecoveryObservationHandler(foreign)
    assert not foreign.exists()


def test_symlink_root_is_not_a_trusted_config_path(tmp_path: Path) -> None:
    root = tmp_path / ("txn-" + NONCE)
    actual = tmp_path / "target"
    actual.mkdir(mode=0o700)
    root.symlink_to(actual, target_is_directory=True)
    with pytest.raises(rpc.RecoveryRPCRefused, match="root not pinned"):
        rpc.RecoveryObservationHandler(root)


def test_external_journal_path_replacement_is_never_adopted(
    tmp_path: Path,
) -> None:
    root = tmp_path / ("txn-" + NONCE)
    root.mkdir(mode=0o700)
    record(root, "guardian_armed")
    h = rpc.RecoveryObservationHandler(root)
    old = root.with_name("old-root")
    root.rename(old)
    root.mkdir(mode=0o700)
    assert h(request())["ok"] is False
    assert (old / "transaction.json").is_file()
    assert not (root / "transaction.lock").exists()


def test_handler_does_not_leak_low_level_exception_details(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from binnacle.platform.darwin import log_maintenance_recovery_rpc as target

    message = "/Users/secret/production.log credential=123"

    def leaked(path: Path):
        raise OSError(message)

    with monkeypatch.context() as m:
        m.setattr(target, "inspect_unowned_transaction", leaked)
        response = rpc.RecoveryObservationHandler(root)(request())
    assert "journal_unavailable" == response["code"]
    assert message not in repr(response)


def test_wire_refuses_non_authority_snapshot(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record(root, "complete")
    illegal = SimpleNamespace(
        transaction_nonce=NONCE,
        phase="complete",
        manual_review_required=False,
        production_authorized=False,
        autonomous_restart_allowed=False,
    )
    with pytest.raises(rpc.RecoveryRPCRefused, match="cannot transmit"):
        rpc._wire(cast(RecoveryAssessment, illegal), 11)
