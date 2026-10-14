"""Strict lsof transcript gates; a complete-looking record never grants pruning."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from binnacle.platform.darwin import log_maintenance_fd_evidence as fd

SOURCE = fd.FDIdentity(Path("/tmp/issue30-source.log"), 66051, 31337)
CANARY = fd.WritableCanary(Path("/tmp/issue30-control.tmp"), 66051, 91011, 723, 8)


def row(*, pid: int, number: int, access: str, path: Path, dev: int, inode: int) -> str:
    return f"p{pid}\nf{number}\na{access}\nD0x{dev:x}\ni{inode}\nn{path}\n"


def base() -> str:
    return row(
        pid=CANARY.pid,
        number=CANARY.fd,
        access="w",
        path=CANARY.path,
        dev=CANARY.device,
        inode=CANARY.inode,
    )


def source_row(
    *,
    access: str = "r",
    pid: int = 1001,
    number: int = 7,
    path: Path = SOURCE.path,
    dev: int = SOURCE.device,
    inode: int = SOURCE.inode,
) -> str:
    return row(pid=pid, number=number, access=access, path=path, dev=dev, inode=inode)


def inspect(
    raw: str,
    *,
    source: fd.FDIdentity = SOURCE,
    canary: fd.WritableCanary = CANARY,
    rc: object = 0,
    stderr: object = "",
) -> fd.FDCensusEvidence:
    return fd.classify_lsof_census(
        stdout=raw,
        stderr=cast(str, stderr),
        returncode=cast(int, rc),
        source=source,
        canary=canary,
    )


def test_positive_control_only_is_not_production_authorization() -> None:
    report = inspect(base())
    assert report.diagnostic == "no_source_writer_observed_advisory_only"
    assert report.observed_readers == ()
    assert report.observed_writers == ()
    assert report.manual_review_required
    assert not report.complete_privileged_fd_census
    assert not report.production_authorized


def test_readers_are_distinguished_from_writers() -> None:
    report = inspect(base() + source_row(access="r"))
    assert report.observed_readers == ((1001, 7),)
    assert report.observed_writers == ()
    assert report.diagnostic == "no_source_writer_observed_advisory_only"
    assert not report.production_authorized


@pytest.mark.parametrize("access", ["w", "u"])
def test_writable_and_readwrite_handles_always_block_automatic_conclusion(
    access: str,
) -> None:
    result = inspect(base() + source_row(access=access))
    assert result.observed_writers == ((1001, 7),)
    assert result.observed_readers == ()
    assert result.diagnostic == "writable_source_fds_observed"
    assert not result.production_authorized


def test_multiple_owner_pids_multiple_fds_and_sorted_records() -> None:
    result = inspect(
        base()
        + source_row(access="r", pid=3000, number=16)
        + source_row(access="w", pid=2000, number=3)
        + source_row(access="u", pid=1999, number=2),
    )
    assert result.observed_readers == ((3000, 16),)
    assert result.observed_writers == ((1999, 2), (2000, 3))
    assert not result.complete_privileged_fd_census


def test_lsof_command_plan_only_fixed_binary_options_and_paths() -> None:
    assert fd.lsof_readonly_argv(SOURCE, CANARY) == (
        "/usr/sbin/lsof",
        "-nP",
        "-F",
        "pafDin",
        "--",
        str(SOURCE.path),
        str(CANARY.path),
    )


@pytest.mark.parametrize(
    "path",
    [
        "relative.log",
        "/tmp/../archive.log",
        "/tmp/a\nb",
        "/tmp/a\rb",
        "/tmp/a\x00b",
    ],
)
def test_untrusted_source_paths_are_refused(path: str) -> None:
    with pytest.raises(fd.FDCensusRefused, match="invalid pinned"):
        fd.FDIdentity(Path(path), SOURCE.device, SOURCE.inode)


@pytest.mark.parametrize("bad", [None, False, True, 0, -1, 1.5, "1"])
def test_invalid_source_device_type_or_value_refused(bad: object) -> None:
    with pytest.raises(fd.FDCensusRefused, match="identity"):
        fd.FDIdentity(SOURCE.path, cast(int, bad), SOURCE.inode)


@pytest.mark.parametrize("bad", [None, True, 0, -10, "99"])
def test_invalid_source_inode_refused(bad: object) -> None:
    with pytest.raises(fd.FDCensusRefused, match="identity"):
        fd.FDIdentity(SOURCE.path, SOURCE.device, cast(int, bad))


@pytest.mark.parametrize(
    ("pid", "fdnum"),
    [
        (0, 8),
        (True, 8),
        (-1, 8),
        ("100", 8),
        (723, -1),
        (723, False),
        (723, 1.5),
    ],
)
def test_untrusted_canary_pid_and_fd_refused(pid: object, fdnum: object) -> None:
    with pytest.raises(fd.FDCensusRefused, match="canary"):
        fd.WritableCanary(
            CANARY.path, CANARY.device, CANARY.inode, cast(int, pid), cast(int, fdnum)
        )


@pytest.mark.parametrize(
    ("source", "canary"),
    [
        (SOURCE, fd.WritableCanary(SOURCE.path, CANARY.device, CANARY.inode, 723, 8)),
        (SOURCE, fd.WritableCanary(CANARY.path, SOURCE.device, SOURCE.inode, 723, 8)),
    ],
)
def test_identical_inode_or_path_cannot_act_as_both_source_and_canary(
    source: fd.FDIdentity, canary: fd.WritableCanary
) -> None:
    with pytest.raises(fd.FDCensusRefused, match="distinct"):
        fd.lsof_readonly_argv(source, canary)
    with pytest.raises(fd.FDCensusRefused, match="distinct"):
        inspect(base(), source=source, canary=canary)


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("", "incomplete"),
        ("p723\n", "truncated"),
        ("p723\nf8\n", "truncated"),
        ("p723\nf8\naw\n", "truncated"),
        ("p723\nf8\naw\nD0x10\n", "truncated"),
        ("p723\nf8\naw\nD0x10\ni20\n", "truncated"),
        (base()[:-1], "incomplete"),
        (base() + "\n", "blank"),
        (base().replace("p723", "p0"), "process boundary"),
        (base().replace("p723", "p-23"), "process boundary"),
        (base().replace("p723", "pNaN"), "process boundary"),
        (base().replace("f8", "f09"), "FD boundary"),
        (base().replace("f8", "f-1"), "FD boundary"),
        (base().replace("f8", "fx"), "FD boundary"),
        (base().replace("aw", "ax"), "identity or access"),
        (base().replace("aw", "auu"), "identity or access"),
        (base().replace("D0x10203", "Dgarbage"), "identity or access"),
        (base().replace("i91011", "i0"), "identity or access"),
        (base().replace("i91011", "iNaN"), "identity or access"),
        (
            base().replace("n/tmp/issue30-control.tmp", "nrelative"),
            "identity or access",
        ),
        (base().replace("aw\nD", "D0x10203\naw\nD"), "field order"),
        ("f8\naw\nD0x10\ni5\nn/tmp/x\n", "FD boundary"),
        (base() + "p123\n", "truncated"),
        (base() + "xunknown\n", "field order"),
        (base() + base(), "duplicate"),
        (base().replace("p723\n", "p723\np234\n"), "process boundary"),
        (base().replace("f8\n", "f8\nf9\n"), "FD boundary"),
        (base().replace("aw\n", "aw\naw\n"), "field order"),
    ],
)
def test_strict_file_descriptor_transcript_parser_refuses_ambiguity(
    raw: str, reason: str
) -> None:
    with pytest.raises(fd.FDCensusRefused, match=reason):
        inspect(raw)


def test_embedded_nul_and_oversized_transcripts_refused() -> None:
    for raw in (base() + "\x00", base() + ("p" * 300000) + "\n"):
        with pytest.raises(fd.FDCensusRefused, match="incomplete or oversized"):
            inspect(raw)


@pytest.mark.parametrize("bad", [0.0, True, False, -1, 2, None, "0"])
def test_nonzero_or_non_integer_exit_refuses_before_transcript(bad: object) -> None:
    with pytest.raises(fd.FDCensusRefused, match="execution"):
        inspect(base(), rc=bad)


@pytest.mark.parametrize("error", ["warning", "\n", "lsof permission denied", False])
def test_any_stderr_or_invalid_stderr_refused(error: object) -> None:
    with pytest.raises(fd.FDCensusRefused, match="execution"):
        inspect(base(), stderr=error)


@pytest.mark.parametrize(
    ("canary_row", "reason"),
    [
        (source_row(), "positive-control"),
        (base().replace("p723", "p724"), "positive-control"),
        (base().replace("f8", "f7"), "positive-control"),
        (base().replace("aw", "ar"), "was not writable"),
        (base().replace("i91011", "i91012"), "canary inode"),
        (base().replace("D0x10203", "D0x10204"), "canary inode"),
    ],
)
def test_canary_must_be_the_actual_pinned_writable_process_fd(
    canary_row: str, reason: str
) -> None:
    with pytest.raises(fd.FDCensusRefused, match=reason):
        inspect(canary_row)


@pytest.mark.parametrize(
    "delta",
    [
        {"dev": SOURCE.device + 1},
        {"inode": SOURCE.inode + 1},
    ],
)
def test_source_inode_change_is_unknown_not_writer_free(delta: dict) -> None:
    with pytest.raises(fd.FDCensusRefused, match="source inode"):
        inspect(base() + source_row(access="r", **delta))


def test_unknown_lsof_file_record_refuses_everything() -> None:
    with pytest.raises(fd.FDCensusRefused, match="unexpected lsof file"):
        inspect(
            base()
            + source_row(
                path=Path("/private/var/log/not-allowlisted.log"),
            )
        )


def test_forged_report_cannot_make_privileged_complete_or_allow_deletion() -> None:
    for field, update in (
        ("manual_review_required", False),
        ("complete_privileged_fd_census", True),
        ("production_authorized", True),
    ):
        kwargs: dict[str, Any] = {field: update}
        with pytest.raises(ValueError, match="cannot grant"):
            fd.FDCensusEvidence(
                SOURCE,
                CANARY,
                (),
                (),
                "no_source_writer_observed_advisory_only",
                **kwargs,
            )


def test_lsof_exit_one_with_canary_only_is_uncertain_not_permission() -> None:
    # Real Linux lsof can emit canary rows and exit 1 when the *other*
    # pathname had no open FD. This never authorizes a production prune.
    result = inspect(base(), rc=1)
    assert result.diagnostic == "source_absent_or_scan_incomplete_advisory_only"
    assert result.observed_writers == ()
    assert result.manual_review_required
    assert not result.complete_privileged_fd_census
    assert result.production_authorized is False


def test_lsof_exit_one_with_actual_source_match_is_unreconciled() -> None:
    with pytest.raises(fd.FDCensusRefused, match="partial-scan"):
        inspect(base() + source_row(access="r"), rc=1)


def test_lsof_exit_one_cannot_mask_missing_canary_positive_control() -> None:
    with pytest.raises(fd.FDCensusRefused, match="positive-control"):
        inspect(source_row(access="r"), rc=1)
