"""Fail-closed launchd label, plist and fd-census parser policy cases."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from binnacle.companions import darwin_log_archive_finalize as finish
from binnacle.companions import darwin_log_writer_hold as writer


@pytest.mark.parametrize(
    ("rc", "out", "err", "result"),
    [
        (0, "system/test = {}", "", True),
        (113, "", 'Could not find service "sample" in domain for system', False),
    ],
)
def test_exact_loaded_vs_unloaded_status(
    monkeypatch: pytest.MonkeyPatch, rc: int, out: str, err: str, result: bool
) -> None:
    monkeypatch.setattr(
        writer,
        "_run",
        lambda args, timeout=12: subprocess.CompletedProcess(args, rc, out, err),
    )
    assert writer._loaded("system/com.binnacle.archivefixture.unit1234") is result


@pytest.mark.parametrize(
    ("rc", "out", "err"),
    [
        (1, "", "not authorized"),
        (113, "", "permission denied"),
        (2, "", "Could not find service"),
    ],
)
def test_indeterminate_launchd_state_refuses(
    monkeypatch: pytest.MonkeyPatch, rc: int, out: str, err: str
) -> None:
    monkeypatch.setattr(
        writer,
        "_run",
        lambda args, timeout=12: subprocess.CompletedProcess(args, rc, out, err),
    )
    with pytest.raises(finish.ArchiveFinalizeRefused, match="unprovable"):
        writer._loaded("system/com.binnacle.archivefixture.unit1234")


@pytest.mark.parametrize(
    ("rc", "response", "expected"),
    [
        (0, "    pid = 4321\n", 4321),
        (0, "    pid = 0\n", None),
        (0, "    pid = 4321\n    pid = 4322\n", None),
        (1, "", None),
        (0, "state = running\n", None),
    ],
)
def test_producer_pid_must_be_single_live_generation(
    monkeypatch: pytest.MonkeyPatch,
    rc: int,
    response: str,
    expected: int | None,
) -> None:
    monkeypatch.setattr(
        writer,
        "_run",
        lambda args, timeout=12: subprocess.CompletedProcess(args, rc, response, ""),
    )
    if expected is None:
        with pytest.raises(finish.ArchiveFinalizeRefused):
            writer._running_pid("system/test")
    else:
        assert writer._running_pid("system/test") == expected


@pytest.mark.parametrize(
    ("rows", "reason"),
    [
        ("pnone\nf3\nar\nn/private/tmp/log\n", "invalid lsof process"),
        ("f3\nar\nn/private/tmp/log\n", "invalid lsof descriptor"),
        ("p123\nf\nar\nn/private/tmp/log\n", "invalid lsof descriptor"),
        ("p123\nf3\nar\nar\nn/private/tmp/log\n", "unknown lsof access"),
        ("p123\nf3\nar\n", "incomplete"),
        ("p123\nf3\nar\nn/private/tmp/log\nf4\n", "incomplete"),
        ("p123\nf3\nar\nn/private/tmp/log\nqgarbage\n", "unexpected lsof"),
    ],
)
def test_lsof_unrecognized_or_incomplete_rows_refuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rows: str, reason: str
) -> None:
    monkeypatch.setattr(
        writer,
        "_run",
        lambda args, timeout=12: subprocess.CompletedProcess(args, 0, rows, ""),
    )
    with pytest.raises(finish.ArchiveFinalizeRefused, match=reason):
        writer._no_writer_fds(tmp_path / "unknown.log")


def test_subprocess_and_lsof_inspection_errors_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def no_subprocess(*args, **kwargs):
        raise subprocess.TimeoutExpired(args, timeout=0.001)

    monkeypatch.setattr(writer.subprocess, "run", no_subprocess)
    with pytest.raises(finish.ArchiveFinalizeRefused, match="unavailable"):
        writer._no_writer_fds(tmp_path / "sample.log")


def _fake_fixture_hold(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> writer.LaunchdFixtureWriterHold:
    monkeypatch.setattr(writer.sys, "platform", "darwin")
    return writer.LaunchdFixtureWriterHold(
        label="com.binnacle.archivefixture.unit1234",
        plist=Path("/private/tmp/com.binnacle.archivefixture.unit1234.plist"),
        log_root=tmp_path,
        name="mcp.stderr.log.0",
    )


def test_cannot_enter_fixture_hold_twice_and_invalid_generation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    hold = _fake_fixture_hold(monkeypatch, tmp_path)
    hold._held = True
    with pytest.raises(finish.ArchiveFinalizeRefused, match="twice"):
        hold.__enter__()
    hold._held = False
    with pytest.raises(finish.ArchiveFinalizeRefused, match="not owned"):
        hold.verify("mcp.stderr.log.0", tmp_path.stat())
    hold._booted_out = True
    with pytest.raises(finish.ArchiveFinalizeRefused, match="twice"):
        hold.__enter__()


@pytest.mark.parametrize(
    ("kind", "details"),
    [
        ("foreign_owner", {"st_uid": 99}),
        ("bad_gid", {"st_gid": 99}),
        ("hardlinked", {"st_nlink": 2}),
        ("unsafe_mode", {"st_mode": 0o100666}),
        ("directory", {"st_mode": 0o40755}),
    ],
)
def test_fixture_plist_owner_and_mode_must_be_authoritative(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    kind: str,
    details: dict[str, int],
) -> None:
    from types import SimpleNamespace

    hold = _fake_fixture_hold(monkeypatch, tmp_path)
    identity = {"st_mode": 0o100644, "st_uid": 0, "st_gid": 0, "st_nlink": 1}
    identity.update(details)
    monkeypatch.setattr(Path, "lstat", lambda self: SimpleNamespace(**identity))
    with pytest.raises(finish.ArchiveFinalizeRefused, match="unsafe"):
        hold._plist_identity()
    assert kind


def test_holder_verifies_exact_source_generation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    raw = tmp_path / "mcp.stderr.log.0"
    raw.write_bytes(b"before")
    hold = _fake_fixture_hold(monkeypatch, tmp_path)
    hold._held = True
    hold._booted_out = True
    monkeypatch.setattr(hold, "_no_writers", lambda: None)
    initial = raw.stat()
    hold.verify(raw.name, initial)
    # Keep the old inode referenced: unlink+recreate can legitimately reuse
    # the same inode immediately on Linux. Renaming avoids that false proof.
    preserved = tmp_path / "old-inode-preserved"
    raw.rename(preserved)
    raw.write_bytes(b"after")
    assert preserved.stat().st_ino == initial.st_ino
    assert raw.stat().st_ino != initial.st_ino
    with pytest.raises(finish.ArchiveFinalizeRefused, match="inode"):
        hold.verify(raw.name, initial)


def test_loaded_label_during_hold_refuses_proof(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    hold = _fake_fixture_hold(monkeypatch, tmp_path)
    monkeypatch.setattr(writer, "_loaded", lambda *_args: True)
    with pytest.raises(finish.ArchiveFinalizeRefused, match="could reopen"):
        hold._no_writers()


def test_bootout_refusal_retains_already_loaded_service(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    hold = _fake_fixture_hold(monkeypatch, tmp_path)
    monkeypatch.setattr(hold, "_plist_identity", lambda: None)
    monkeypatch.setattr(writer, "_loaded", lambda *_args: True)
    monkeypatch.setattr(writer, "_running_pid", lambda *_args: 18)
    monkeypatch.setattr(
        writer,
        "_run",
        lambda args, timeout=12: subprocess.CompletedProcess(args, 1, "", "error"),
    )
    with pytest.raises(finish.ArchiveFinalizeRefused, match="refused"):
        hold.__enter__()
    assert not hold._booted_out
    assert not hold._held


def test_restore_failure_remains_explicit_and_does_not_claim_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    hold = _fake_fixture_hold(monkeypatch, tmp_path)
    hold._booted_out = True
    hold._held = True
    monkeypatch.setattr(writer, "_loaded", lambda *_args: False)
    monkeypatch.setattr(hold, "_plist_identity", lambda: None)
    monkeypatch.setattr(
        writer,
        "_run",
        lambda args, timeout=12: subprocess.CompletedProcess(args, 3, "", "refused"),
    )
    with pytest.raises(finish.ArchiveFinalizeRefused, match="restoration failed"):
        hold._restore()
    assert hold._booted_out  # recovery still required
    assert not hold._held
