"""A5 private service-log epochs, cursors, budgets, crash gaps and redaction.

Portable POSIX mechanics (flock, O_NOFOLLOW, descriptor fstat), so the same
assertions run on Darwin and Linux; nothing here touches launchd or journald.
"""

from __future__ import annotations

import dataclasses
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from binnacle.platform.contracts.capability_contracts import (
    AuthorityUnknown,
    BudgetExceeded,
    CapabilityState,
    CursorExpired,
    UnsafePath,
)
from binnacle.platform.contracts.metric_log_contracts import CursorLogSource, LogCursor
from binnacle.platform.contracts.service_log_contracts import (
    ServiceLogError,
    ServiceLogSource,
)
from binnacle.platform.darwin import log_cursor, log_source
from binnacle.platform.darwin.log_cursor import (
    HEADER_LEN,
    load_cursor,
    load_manifest,
    save_cursor,
    validate_cursor,
)
from binnacle.platform.darwin.log_source import (
    MAX_RECORD_BYTES,
    PrivateServiceLogSource,
    PrivateServiceLogWriter,
)

GEN = "gen-a"
SERVICE = "binnacle-test"
# Assembled at runtime so secret scanners never see a literal credential.
SENTINELS = {
    "registered": "reg" + "istered-" + "s3ntinel-0042", "bearer": "beare" + "rtok-77z",
    "password": "pw" + "-sentinel-91", "url": "urlpw" + "-sentinel-13",
    "github": "gh" + "p_" + "Q" * 30, "pem": "pem" + "-body-sentinel",
}  # fmt: skip
# The writer process dies without close(); the kernel drops its flock.
CRASH_SCRIPT = (
    "import os, sys, pathlib; from binnacle.platform.darwin.log_source import "
    "PrivateServiceLogWriter as W; w = W(root=pathlib.Path(sys.argv[1]), "
    "generation=sys.argv[2], service=sys.argv[3]); w.start(); "
    "w.write('before crash'); os._exit(0)"
)


def crash(root: Path) -> None:
    command = [sys.executable, "-c", CRASH_SCRIPT, str(root), GEN, SERVICE]
    subprocess.run(command, check=True, timeout=60)


class Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def start(root: Path, *, generation: str = GEN, **kwargs) -> PrivateServiceLogWriter:
    writer = PrivateServiceLogWriter(
        root=root, generation=generation, service=SERVICE, **kwargs
    )
    writer.start()
    return writer


def read(source, cursor=None, *, max_bytes=65536, max_lines=1000):
    return source.read_cursor(SERVICE, cursor, max_bytes=max_bytes, max_lines=max_lines)


def texts(data: bytes) -> list[str]:
    return [line.split(" ", 1)[1] for line in data.decode().splitlines()]


def drain(source, cursor=None):
    """Follow cursors to the current end; return texts, final cursor, gaps."""
    out, gaps = [], []
    while True:
        batch = read(source, cursor)
        gaps.append(batch.gap)
        cursor = batch.next_cursor
        if not batch.data:
            return out, cursor, gaps
        out += texts(batch.data)


def expired_reason(call) -> str:
    with pytest.raises(CursorExpired, match="log_cursor_expired") as excinfo:
        call()
    return excinfo.value.capability.reason_code


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "logs"


@pytest.fixture
def writer(root: Path):
    owned = start(root, clock=Clock())
    yield owned
    owned.close()  # idempotent; tests may close earlier


@pytest.fixture
def source(root: Path) -> PrivateServiceLogSource:
    return PrivateServiceLogSource(root=root, generation=GEN)  # no I/O until read


def test_private_modes_header_and_ordered_cursor_reads(root, writer, source):
    for word in ("one", "two", "three"):
        writer.write(word)
    service_dir = root / SERVICE
    for path in (root, service_dir):
        assert stat.S_IMODE(path.stat().st_mode) == 0o700
    for path in service_dir.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600, path.name
    header = f"#binnacle-log-epoch {writer.epoch}\n".encode()
    assert (service_dir / f"{writer.epoch}.log").read_bytes().startswith(header)
    as_window: ServiceLogSource = source  # implements both log protocols
    as_cursor: CursorLogSource = source
    first = read(as_cursor, max_lines=2)
    assert as_window.read_window([SERVICE], 1000.0) == "one\ntwo\nthree\n"
    assert texts(first.data) == ["one", "two"]
    assert first.truncated and not first.gap
    assert first.capability.state is CapabilityState.LIMITED
    assert first.next_cursor.stream_epoch == writer.epoch
    rest = read(source, first.next_cursor)
    assert texts(rest.data) == ["three"] and not rest.truncated
    assert read(source, rest.next_cursor).data == b""


def test_byte_budget_keeps_whole_records_and_caps_are_typed(root, writer, source):
    writer.write("a" * 40)
    writer.write("b" * 40)
    batch = read(source, max_bytes=70)
    assert texts(batch.data) == ["a" * 40] and batch.truncated
    tiny = read(source, max_bytes=10)
    assert len(tiny.data) == 10 and tiny.truncated  # one record over budget splits
    with pytest.raises(BudgetExceeded) as excinfo:
        read(source, max_bytes=log_cursor.MAX_READ_BYTES + 1)
    assert excinfo.value.capability.state is CapabilityState.UNAVAILABLE
    with pytest.raises(BudgetExceeded):
        read(source, max_lines=log_cursor.MAX_READ_LINES + 1)
    for bad in (0, -1, True, 1.5):
        with pytest.raises(ValueError, match="budget"):
            read(source, max_bytes=bad)


def test_in_progress_record_of_live_epoch_is_withheld(root, writer, source):
    writer.write("whole")
    with open(root / SERVICE / f"{writer.epoch}.log", "ab") as handle:
        handle.write(b"1000.5 partial-without-newline")
    batch = read(source)
    assert texts(batch.data) == ["whole"] and not batch.truncated
    assert read(source, batch.next_cursor).data == b""


def test_rotation_issues_new_epoch_and_cursor_crosses_without_gap(root, source):
    writer = start(root, clock=Clock(), max_epoch_bytes=HEADER_LEN + (16 << 10) + 64)
    writer.write("before")
    old_epoch = writer.epoch
    held = read(source).next_cursor
    bulk = [f"bulk-{index:04d}-" + "x" * 30 for index in range(450)]
    for text in bulk:
        writer.write(text)  # about 22 KiB: crosses the size limit once
    writer.rotate()
    writer.write("after")
    assert writer.epoch != old_epoch
    words, cursor, gaps = drain(source, held)
    assert words == [*bulk, "after"]
    assert cursor.stream_epoch == writer.epoch and not any(gaps)
    entries = load_manifest(root / SERVICE, SERVICE).entries
    assert [e.end for e in entries] == ["rotated", "rotated", "open"]
    assert all(e.final_size <= writer._max_epoch_bytes for e in entries[:2])
    writer.close()


def test_clean_restart_new_epoch_old_cursor_continues(root, writer, source):
    writer.write("first-life")
    writer.close()
    words, cursor, _ = drain(source)
    assert words == ["first-life"]
    restarted = start(root, clock=Clock(2000.0))
    restarted.write("second-life")
    assert restarted.epoch != cursor.stream_epoch
    words, after, gaps = drain(source, cursor)
    assert words == ["second-life"] and not any(gaps)
    # A forged cursor that names the restarted epoch with the old inode expires.
    forged = dataclasses.replace(after, inode=cursor.inode)
    assert expired_reason(lambda: read(source, forged)) == "inode_mismatch"
    restarted.close()


def test_crash_is_a_gap_never_seamless_continuity(root, source):
    crash(root)
    started = load_manifest(root / SERVICE, SERVICE).entries[0].started_at
    with pytest.raises(ServiceLogError, match="window_overlaps_crash_gap"):
        source.read_window([SERVICE], started)
    words, cursor, gaps = drain(source)
    assert words == ["before crash"] and not any(gaps)
    writer = start(root)
    writer.write("recovered")
    batch = read(source, cursor)
    assert texts(batch.data) == ["recovered"] and batch.gap
    assert batch.capability.state is CapabilityState.UNKNOWN
    assert batch.capability.reason_code == "log_gap_coverage_unknown"
    ends = [e.end for e in load_manifest(root / SERVICE, SERVICE).entries]
    assert ends == ["crashed", "open"]
    with pytest.raises(ServiceLogError, match="window_overlaps_crash_gap"):
        source.read_window([SERVICE], started)
    writer.close()


def test_pruned_epoch_expires_cursor_and_fresh_read_reports_gap(root, source):
    clock = Clock()
    writer = start(root, clock=clock, retain_epochs=1)
    writer.write("old")
    old_cursor = read(source).next_cursor
    clock.now = 1100.0
    writer.rotate()
    writer.write("new")
    assert not (root / SERVICE / f"{old_cursor.stream_epoch}.log").exists()
    assert expired_reason(lambda: read(source, old_cursor)) == "epoch_pruned"
    fresh = read(source)
    assert texts(fresh.data) == ["new"] and fresh.gap
    with pytest.raises(ServiceLogError, match="window_overlaps_pruned_epoch"):
        source.read_window([SERVICE], 1000.0)
    assert source.read_window([SERVICE], 1100.0) == "new\n"
    writer.close()


def test_truncation_and_replacement_expire_cursors(root, writer, source):
    writer.write("alpha")
    writer.write("beta")
    cursor = read(source).next_cursor
    path = root / SERVICE / f"{writer.epoch}.log"
    os.truncate(path, HEADER_LEN + 4)
    assert expired_reason(lambda: read(source, cursor)) == "offset_beyond_end"
    os.truncate(path, 0)
    assert expired_reason(lambda: read(source)) == "epoch_header_mismatch"
    path.unlink()
    path.write_bytes(b"#foreign\n")
    path.chmod(0o600)
    assert expired_reason(lambda: read(source)) == "epoch_file_replaced"
    path.unlink()
    path.symlink_to(root / SERVICE / "manifest.json")
    assert expired_reason(lambda: read(source)) == "epoch_file_missing"


def test_closed_epoch_size_change_is_detected(root, writer, source):
    writer.write("sealed")
    epoch = writer.epoch
    writer.close()
    with open(root / SERVICE / f"{epoch}.log", "ab") as handle:
        handle.write(b"1000.0 appended-after-close\n")
    assert expired_reason(lambda: read(source)) == "epoch_size_mismatch"
    with pytest.raises(ServiceLogError, match="epoch_size_mismatch"):
        source.read_window([SERVICE], 1000.0)


def test_live_truncate_and_regrow_is_undetectable_by_size(root, writer, source):
    """Documented limit: only the writer's never-truncate rule prevents this."""
    writer.write("original")
    cursor = read(source).next_cursor
    path = root / SERVICE / f"{writer.epoch}.log"
    header = path.read_bytes()[:HEADER_LEN]
    # The regrown first record has the original's length, so the old offset
    # lands on a record boundary and unrelated bytes are silently stitched.
    path.write_bytes(header + b"1000.0 regrown-xxxxx\n1000.0 more\n")
    assert texts(read(source, cursor).data) == ["more"]


def test_foreign_generation_and_missing_records_are_unknown_not_empty(root, source):
    root.mkdir(mode=0o700)
    (root / SERVICE).mkdir(mode=0o700)
    with pytest.raises(AuthorityUnknown) as excinfo:
        read(source)
    assert excinfo.value.capability.state is CapabilityState.UNKNOWN
    with pytest.raises(ServiceLogError, match="log_coverage_unknown"):
        source.read_window([SERVICE], 0.0)
    writer = start(root, generation="gen-b", clock=Clock())
    writer.write("other generation")
    with pytest.raises(AuthorityUnknown):
        read(source)
    other = PrivateServiceLogSource(root=root, generation="gen-b")
    cursor = read(other).next_cursor
    assert expired_reason(lambda: read(source, cursor)) == "generation_mismatch"
    with pytest.raises(ServiceLogError, match="window_precedes_coverage"):
        other.read_window([SERVICE], 999.0)
    writer.close()


FOREIGN = b'{"schema":"other","service":"x","entries":[],"coverage_lost_before":null}'


@pytest.mark.parametrize("manifest", [b"{not json", b"[]", FOREIGN])
def test_corrupt_or_foreign_manifest_is_unknown(root, writer, manifest, source):
    writer.close()
    (root / SERVICE / "manifest.json").write_bytes(manifest)
    with pytest.raises(AuthorityUnknown):
        read(source)
    with pytest.raises(ServiceLogError):
        source.read_window([SERVICE], 1000.0)
    with pytest.raises(AuthorityUnknown):
        start(root)  # a writer never overwrites contradictory bookkeeping


def test_non_private_or_symlinked_roots_are_refused(root, writer, tmp_path, source):
    writer.write("x")
    writer.close()
    root.chmod(0o755)
    with pytest.raises(UnsafePath):
        read(source)
    root.chmod(0o700)
    link = tmp_path / "linked"
    link.symlink_to(root)
    with pytest.raises(UnsafePath):
        read(PrivateServiceLogSource(root=link, generation=GEN))
    with pytest.raises(UnsafePath):
        source.read_cursor("../escape", None, max_bytes=10, max_lines=1)


def test_redaction_happens_before_persistence(root, source):
    s = SENTINELS
    writer = start(root, clock=Clock(), redact_values=[s["registered"]])
    writer.write(f"user token {s['registered']} used")
    writer.write(f"Authorization: Bearer {s['bearer']}")
    writer.write(f'{{"password": "{s["password"]}"}}')
    writer.write(f"fetch https://alice:{s['url']}@example.invalid/x")
    writer.write(f"leaked {s['github']}")
    writer.write(f"-----BEGIN PRIVATE KEY-----\n{s['pem']}\n-----END PRIVATE KEY-----")
    writer.write("line1\nforged 9999.0 record\x1b[31m")
    writer.close()
    blob = b"".join(p.read_bytes() for p in (root / SERVICE).iterdir())
    assert not [value for value in s.values() if value.encode() in blob]
    lines = texts(read(source).data)
    assert len(lines) == 7  # embedded newlines cannot forge extra records
    assert lines[6] == "line1\\nforged 9999.0 record\\x1b[31m"
    assert all("[redacted]" in line for line in lines[:6])


def test_errors_never_echo_secret_bearing_input(root, source):
    secret = SENTINELS["registered"]
    for call in (
        lambda: source.read_window([secret], 0.0),
        lambda: source.read_cursor(secret + "/x", None, max_bytes=1, max_lines=1),
        lambda: PrivateServiceLogSource(root=root, generation=secret + "/"),
    ):
        with pytest.raises((ServiceLogError, UnsafePath)) as excinfo:
            call()
        assert secret not in str(excinfo.value)
        assert str(root) not in str(excinfo.value)


def test_read_window_filters_merges_and_bounds(root, monkeypatch, source):
    clocks = {"svc-a": Clock(1000.0), "svc-b": Clock(1000.5)}
    writers = {name: PrivateServiceLogWriter(root=root, generation=GEN, service=name, clock=clocks[name]) for name in clocks}  # fmt: skip
    for writer in writers.values():
        writer.start()
    timeline = [(1001.2, "svc-a", "a1"), (1001.7, "svc-b", "b1"), (1003.9, "svc-a", "a2"), (1005.0, "svc-b", "b2")]  # fmt: skip
    for at, name, text in timeline:
        clocks[name].now = at
        writers[name].write(text)
    assert source.read_window(["svc-a", "svc-b"], 1000.6) == "a1\nb1\na2\nb2\n"
    assert source.read_window(["svc-a", "svc-b"], 1000.6, 1003.2) == "a1\nb1\na2\n"
    with pytest.raises(ServiceLogError, match="window_precedes_coverage"):
        source.read_window(["svc-a", "svc-b"], 1000.2)
    for bad in ([], "svc-a"):
        with pytest.raises(ServiceLogError, match="services_required"):
            source.read_window(bad, 1001.0)
    with pytest.raises(ServiceLogError, match="window_invalid"):
        source.read_window(["svc-a"], float("nan"))
    monkeypatch.setattr("binnacle.platform.darwin.log_source.WINDOW_MAX_LINES", 1)
    with pytest.raises(ServiceLogError, match="window_exceeds_read_budget"):
        source.read_window(["svc-a"], 1000.6)
    for writer in writers.values():
        writer.close()


def test_single_writer_and_positive_descriptor_cleanup(root, writer):
    with pytest.raises(ServiceLogError, match="writer_already_active"):
        start(root)
    descriptors = [writer._fd, writer._lock_fd]
    writer.close()
    for fd in descriptors:
        with pytest.raises(OSError):
            os.fstat(fd)
    assert writer.epoch is None
    writer.close()  # idempotent
    with pytest.raises(ServiceLogError, match="writer_not_active"):
        writer.write("late")
    start(root).close()  # the released lock admits a successor


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"service_generation": "gen-b"}, "generation_mismatch"), ({"stream_epoch": "f" * 32}, "epoch_mismatch"),
        ({"device": 9}, "inode_mismatch"), ({"inode": 9}, "inode_mismatch"),
        ({"offset": -1}, "offset_negative"), ({"offset": 101}, "offset_beyond_end"),
        ({"offset": True}, "cursor_malformed"), ({"stream_epoch": "../x"}, "cursor_malformed"),
    ],
)  # fmt: skip
def test_validate_cursor_rejections(change, reason):
    good = LogCursor(GEN, "e" * 32, 1, 2, 50)
    validate_cursor(good, generation=GEN, epoch="e" * 32, device=1, inode=2, size=100)
    bad = dataclasses.replace(good, **change)
    assert expired_reason(lambda: validate_cursor(bad, generation=GEN, epoch="e" * 32, device=1, inode=2, size=100)) == reason  # fmt: skip


def test_durable_cursor_round_trip_and_strict_parsing(root, writer, source):
    writer.write("persisted")
    state = root / "cursor-state"
    state.mkdir(mode=0o700)
    path = state / "cursor.json"
    assert load_cursor(path) is None
    save_cursor(path, read(source).next_cursor)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    writer.write("after restart")
    restarted = PrivateServiceLogSource(root=root, generation=GEN)
    assert texts(read(restarted, load_cursor(path)).data) == ["after restart"]
    body = json.loads(path.read_bytes())
    variants = [{**body, "extra": 1}, {**body, "offset": -5}, {**body, "device": False}, {**body, "schema": "v0"}]  # fmt: skip
    for bad in (b"{", b"x" * 2000, *(json.dumps(v).encode() for v in variants)):
        path.write_bytes(bad)
        path.chmod(0o600)
        with pytest.raises((CursorExpired, UnsafePath)):
            load_cursor(path)
    path.chmod(0o644)
    with pytest.raises(UnsafePath):
        load_cursor(path)
    path.unlink()
    path.symlink_to(root / SERVICE / "manifest.json")
    with pytest.raises(UnsafePath):
        load_cursor(path)
    state.chmod(0o755)
    with pytest.raises(UnsafePath):
        save_cursor(state / "other.json", LogCursor(GEN, "e" * 32, 1, 2, 3))


def test_writer_bounds_records_and_refuses_misuse(root, writer, source):
    with pytest.raises(ServiceLogError, match="identifier_invalid"):
        PrivateServiceLogWriter(root=root, generation="../g", service=SERVICE)
    with pytest.raises(ValueError, match="too small"):
        start(root, max_epoch_bytes=HEADER_LEN)
    with pytest.raises(ServiceLogError, match="writer_already_started"):
        writer.start()
    writer.write("y" * (20 << 10))
    writer.sync()
    data = read(source).data
    assert data.endswith(b" [truncated]\n") and len(data) <= MAX_RECORD_BYTES
    writer.close()
    with pytest.raises(ServiceLogError, match="writer_not_active"):
        writer.rotate()


def test_lost_crash_epoch_and_dropped_history_are_gaps(root, monkeypatch, source):
    crash(root)
    lost = load_manifest(root / SERVICE, SERVICE).entries[0]
    (root / SERVICE / lost.file_name).unlink()  # crash evidence itself vanished
    writer = start(root)
    writer.write("kept")
    first, current = load_manifest(root / SERVICE, SERVICE).entries
    assert first.pruned and first.end == "crashed"
    restarted_at = current.started_at
    words, _, gaps = drain(source)
    assert words == ["kept"] and gaps[0]
    with pytest.raises(ServiceLogError, match="window_overlaps_crash_gap"):
        source.read_window([SERVICE], lost.started_at)
    with open(root / SERVICE / f"{writer.epoch}.log", "ab") as handle:
        handle.write(b"not-a-time record\n")
    with pytest.raises(ServiceLogError, match="record_malformed"):
        source.read_window([SERVICE], restarted_at + 1)  # parsed even if outside
    writer.close()
    monkeypatch.setattr(log_source, "MAX_MANIFEST_ENTRIES", 1)
    trimmed = start(root, retain_epochs=1)
    manifest = load_manifest(root / SERVICE, SERVICE)
    assert len(manifest.entries) == 1 and manifest.coverage_lost_before is not None
    assert read(source).gap  # forgotten history is never reported as complete
    with pytest.raises(ServiceLogError, match="window_precedes_coverage"):
        source.read_window([SERVICE], manifest.coverage_lost_before)
    trimmed.close()
