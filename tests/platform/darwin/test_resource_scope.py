"""A5 honest Darwin metrics and secret-free private service logs.

Metrics: typed unavailable totals, measured narrow scopes. Logs: no credential
shape, registered literal or free-text value reaches disk or a read.

The real direct-child test spawns one child and is itself the sole reaper,
handing its final ``wait4`` rusage to the accounting, exactly as the owning
reaper must. Assertions are portable; ru_maxrss units are normalized per OS.
"""

from __future__ import annotations

import ast
import os
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

import pytest

from binnacle.platform.contracts.capability_contracts import CapabilityState, UnsafePath
from binnacle.platform.contracts.metric_log_contracts import MetricValue, ScopedMetrics
from binnacle.platform.contracts.resource_contracts import (
    NoResourceAccounting,
    ResourceAccounting,
)
from binnacle.platform.contracts.service_log_contracts import ServiceLogError
from binnacle.platform.darwin import log_source, resource_accounting
from binnacle.platform.darwin.log_cursor import load_manifest
from binnacle.platform.darwin.log_source import PrivateServiceLogSource
from binnacle.platform.darwin.resource_accounting import DarwinResourceAccounting
from tests.platform.darwin.test_log_epochs import (
    GEN,
    SERVICE,
    Clock,
    drain,
    read,
    start,
    texts,
)

# CAPABILITY-DECISION 1.1.0 scope_decision.unavailable_in_this_revision (A5 rows).
UNAVAILABLE_N6 = {
    "N6.private_libproc_samples", "N6.cpu.stat.usage_usec", "N6.cpu.stat.user_usec",
    "N6.cpu.stat.system_usec", "N6.memory.current", "N6.memory.peak", "N6.pids.current",
    "N6.io.stat.rbytes", "N6.io.stat.wbytes", "N6.memory.events.oom",
    "N6.scope.wait_empty", "N6.resource_history.final", "N6.memory.stat",
    "N6.memory.swap.current", "N6.memory.swap.peak", "N6.memory.swap.events",
    "N6.pids.peak", "N6.processes", "N6.io.stat.rios/wios", "N6.memory.events.oom_kill",
}  # fmt: skip
DIRECT_KEYS = (
    "direct_child.cpu.user_usec",
    "direct_child.cpu.system_usec",
    "direct_child.memory.maxrss_bytes",
)
SELF_KEYS = ("self.cpu.user_usec", "self.cpu.system_usec", "self.memory.maxrss_bytes")
CHILD = (
    "import time\n"
    "block = bytearray(48 << 20)\n"  # resident: pages are touched below
    "block[:: 4096] = b'x' * len(block[:: 4096])\n"
    "end = time.process_time() + 0.25\n"
    "while time.process_time() < end:\n"
    "    pass\n"
)


def rusage(utime=0.5, stime=0.25, maxrss=1000):
    return SimpleNamespace(ru_utime=utime, ru_stime=stime, ru_maxrss=maxrss)


def assert_never_invented(values: Mapping[str, MetricValue]) -> None:
    for key, metric in values.items():
        assert metric.unit and metric.scope in ("self", "direct_child", "job"), key
        if metric.capability.state in (
            CapabilityState.UNKNOWN,
            CapabilityState.UNAVAILABLE,
        ):
            assert metric.value is None, key  # never zero
            assert metric.sampled_at_epoch is None and metric.final is False, key
        else:
            assert metric.capability.state is CapabilityState.LIMITED, key
            assert isinstance(metric.value, int) and metric.value >= 0, key
        assert metric.capability.state is not CapabilityState.AVAILABLE, key


@pytest.mark.parametrize("identity", [None, "", "/legacy/job-012345abcdef"])
def test_legacy_facade_matches_no_accounting_and_invents_no_cgroup(identity):
    darwin: ResourceAccounting = DarwinResourceAccounting()
    legacy: ResourceAccounting = NoResourceAccounting()
    argv = ["bash", "-c", "two words"]
    for port in (darwin, legacy):
        assert port.prepare() is None and port.prepare(log_ready=True) is None
        assert port.create("012345abcdef") is None
        assert port.wrap_argv(argv, identity) is argv
        assert port.snapshot(identity) == {}
        assert port.wait_empty("/legacy/job-012345abcdef") is False
        assert port.cleanup(identity) is (identity is None)
    assert argv == ["bash", "-c", "two words"]


@pytest.mark.parametrize("job_id", [None, "012345abcdef"])
def test_every_job_wide_total_is_typed_unavailable_never_zero(job_id):
    scoped: ScopedMetrics = DarwinResourceAccounting()
    values = scoped.snapshot_scoped(job_id)
    job = {key: metric for key, metric in values.items() if metric.scope == "job"}
    assert {m.capability.evidence_id for m in job.values()} == UNAVAILABLE_N6
    for key, metric in job.items():
        assert key.startswith("job.")
        assert metric.capability.state is CapabilityState.UNAVAILABLE
        assert metric.capability.reason_code == "darwin_job_scope_unavailable"
        assert "no complete Darwin job-membership" in metric.capability.scope
        assert metric.value is None
    assert values["job.scope.empty"].value is None  # no empty-scope proof
    assert values["job.memory.peak_bytes"].value is None  # no aggregate peak
    assert_never_invented(values)


def test_self_scope_is_measured_and_labelled_self_only():
    values = DarwinResourceAccounting().snapshot_scoped()
    for key in SELF_KEYS:
        metric = values[key]
        assert metric.capability.state is CapabilityState.LIMITED
        assert metric.capability.reason_code == "measured_self_getrusage"
        assert metric.scope == "self" and metric.final is False
        assert metric.sampled_at_epoch is not None
    assert values["self.memory.maxrss_bytes"].value > 1 << 20  # bytes, not KiB
    assert not any(key.startswith("direct_child.") for key in values)
    assert_never_invented(values)


def test_missing_record_is_unknown_not_zero():
    values = DarwinResourceAccounting().snapshot_scoped("012345abcdef")
    for key in DIRECT_KEYS:
        metric = values[key]
        assert metric.capability.state is CapabilityState.UNKNOWN
        assert metric.capability.reason_code == "direct_child_observation_missing"
        assert metric.value is None and metric.scope == "direct_child"
    assert not any(key.startswith("self.") for key in values)
    assert_never_invented(values)


def test_restarted_accounting_loses_samples_as_unknown():
    before = DarwinResourceAccounting()
    before.record_direct_child_exit("job-1", rusage(), observed_at=1234.5)
    assert before.snapshot_scoped("job-1")[DIRECT_KEYS[0]].value == 500_000
    restarted = DarwinResourceAccounting()  # a new owner generation
    metric = restarted.snapshot_scoped("job-1")[DIRECT_KEYS[0]]
    assert metric.capability.state is CapabilityState.UNKNOWN and metric.value is None


def test_measured_zero_is_kept_only_for_an_observed_value():
    accounting = DarwinResourceAccounting()
    accounting.record_direct_child_exit("job-0", rusage(0.0, 0.0, 0), observed_at=1.0)
    values = accounting.snapshot_scoped("job-0")
    for key in DIRECT_KEYS:
        assert values[key].capability.state is CapabilityState.LIMITED
        assert values[key].value == 0 and values[key].final is True
    assert_never_invented(values)


def test_real_direct_child_wait4_counters_from_the_single_reaper():
    accounting = DarwinResourceAccounting()
    pid = os.posix_spawn(
        sys.executable, [sys.executable, "-c", CHILD], dict(os.environ)
    )
    reaped, status, usage = os.wait4(pid, 0)  # this test is the sole reaper
    assert reaped == pid and os.waitstatus_to_exitcode(status) == 0
    accounting.record_direct_child_exit("job-real", usage, observed_at=42.0)
    values = accounting.snapshot_scoped("job-real")
    user = values["direct_child.cpu.user_usec"]
    assert user.capability.state is CapabilityState.LIMITED
    assert user.capability.reason_code == "measured_direct_child_wait4"
    assert user.capability.evidence_id == "N6.direct_child_wait4"
    assert "never a job total" in user.capability.scope
    assert user.final is True and user.sampled_at_epoch == 42.0
    total_cpu = user.value + values["direct_child.cpu.system_usec"].value
    assert total_cpu >= 200_000
    assert values["direct_child.memory.maxrss_bytes"].value >= 48 << 20
    assert values["job.cpu.usage_usec"].value is None  # still not a job total
    assert_never_invented(values)
    with pytest.raises(ValueError, match="already recorded"):
        accounting.record_direct_child_exit("job-real", usage)  # no second collector


def test_invalid_observations_are_refused_without_recording():
    accounting = DarwinResourceAccounting()
    bad = [
        (rusage(utime=-1.0), ValueError),
        (rusage(stime=float("nan")), ValueError),
        (rusage(maxrss=-5), ValueError),
        (rusage(utime="1"), TypeError),
        (rusage(maxrss=True), TypeError),
        (object(), TypeError),
    ]
    for observation, error in bad:
        with pytest.raises(error):
            accounting.record_direct_child_exit("job-x", observation)
    with pytest.raises(ValueError, match="job_id"):
        accounting.record_direct_child_exit("", rusage())
    with pytest.raises(ValueError):
        accounting.record_direct_child_exit("job-x", rusage(), observed_at=float("inf"))
    metric = accounting.snapshot_scoped("job-x")[DIRECT_KEYS[0]]
    assert metric.capability.state is CapabilityState.UNKNOWN


def test_positive_cleanup_and_bounded_retention(monkeypatch):
    monkeypatch.setattr(resource_accounting, "MAX_RECORDED_JOBS", 2)
    accounting = DarwinResourceAccounting()
    for job in ("a", "b", "c"):
        accounting.record_direct_child_exit(job, rusage(), observed_at=1.0)
    evicted = accounting.snapshot_scoped("a")[DIRECT_KEYS[0]]
    assert evicted.capability.state is CapabilityState.UNKNOWN  # evicted, not zero
    assert accounting.discard_job("b") is True
    assert accounting.discard_job("b") is False
    assert accounting.snapshot_scoped("b")[DIRECT_KEYS[0]].value is None
    assert accounting.snapshot_scoped("c")[DIRECT_KEYS[0]].value == 500_000


def test_module_never_waits_signals_or_samples_private_libproc():
    source = Path(resource_accounting.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {
        "wait", "wait3", "wait4", "waitpid", "waitid", "kill", "killpg",
        "posix_spawn", "fork", "CDLL", "cdll", "proc_pidinfo", "proc_pid_rusage",
    }  # fmt: skip
    called = {
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Attribute, ast.Name))
    }
    assert not called & forbidden
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not imported & {"ctypes", "subprocess", "signal", "cffi"}


def test_rerecord_after_eviction_refused(monkeypatch):
    monkeypatch.setattr(resource_accounting, "MAX_RECORDED_JOBS", 2)
    monkeypatch.setattr(resource_accounting, "MAX_TOMBSTONES", 4)
    accounting = DarwinResourceAccounting()
    for job in ("a", "b", "c"):
        accounting.record_direct_child_exit(job, rusage(), observed_at=1.0)
    evicted = accounting.snapshot_scoped("a")[DIRECT_KEYS[0]]
    assert evicted.capability.state is CapabilityState.UNKNOWN and evicted.value is None
    assert evicted.capability.reason_code == "direct_child_observation_evicted"
    with pytest.raises(ValueError, match="already recorded"):
        accounting.record_direct_child_exit("a", rusage())  # competing collector
    assert accounting.discard_job("c") is True
    with pytest.raises(ValueError, match="already recorded"):
        accounting.record_direct_child_exit("c", rusage())
    never = accounting.snapshot_scoped("z")[DIRECT_KEYS[0]]
    assert never.capability.reason_code == "direct_child_observation_missing"
    assert all(type(k) is bytes and len(k) == 16 for k in accounting._tombstones)
    for job in ("d", "e"):  # documented bound: the oldest tombstone is forgotten
        accounting.record_direct_child_exit(job, rusage(), observed_at=1.0)
    accounting.record_direct_child_exit("a", rusage(), observed_at=2.0)
    assert accounting.snapshot_scoped("a")[DIRECT_KEYS[0]].sampled_at_epoch == 2.0


# --- No secret logs (R2P-A5-01). These private-log redaction tests live here
# because the frozen 1.1.0 path allowlist admits no new A5 test file and
# test_log_epochs.py is at the 500-line module-size ratchet.


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "logs"


@pytest.fixture
def source(root: Path) -> PrivateServiceLogSource:
    return PrivateServiceLogSource(root=root, generation=GEN)


def pem(edge: str, kind: str = "") -> str:
    """PEM armour assembled at runtime so scanners never see a literal key."""
    return f"-----{edge} {kind}PRIVATE " + "KEY-----"


# Assembled at runtime so secret scanners never see a literal credential.
SENTINELS = {
    "registered": "reg" + "istered-" + "s3ntinel-0042", "bearer": "beare" + "rtok-77z",
    "password": "pw" + "-sentinel-91", "url": "urlpw" + "-sentinel-13",
    "github": "gh" + "p_" + "Q" * 30, "pem": "pem" + "-body-sentinel",
}  # fmt: skip


def test_redaction_happens_before_persistence(root, source):
    s = SENTINELS
    writer = start(root, clock=Clock(), redact_values=[s["registered"]])
    writer.write(f"user token {s['registered']} used")
    writer.write(f"Authorization: Bearer {s['bearer']}")
    writer.write(f'{{"password": "{s["password"]}"}}')
    writer.write(f"fetch https://alice:{s['url']}@example.invalid/x")
    writer.write(f"leaked {s['github']}")
    writer.write(f"{pem('BEGIN')}\n{s['pem']}\n{pem('END')}")
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


# R2P-A5-01 reviewer shapes. Sentinels are assembled at runtime; the low-entropy
# one proves the structural rules without the high-entropy backstop.
REVIEWER_SENTINEL = "S3CR3T-" + "SENTINEL-7f1c"
PLAIN_SENTINEL = "plain" + "words"
SECRET_SHAPES = {
    "argv_list_flag": "spawn argv=['mysql','--password','{s}']",
    "argv_flag_space": "tool --password {s} --verbose",
    "argv_flag_equals": "tool --api-key={s}",
    "curl_user_pass": "curl -u admin {s} https://x",
    "short_p_attached": "mysql -p{s} db",
    "cookie": "Cookie: session={s}",
    "set_cookie": "Set-Cookie: sid={s}; HttpOnly",
    "x_api_key": "X-Api-Key: {s}",
    "authorization_bearer": "Authorization: Bearer {s}",
    "bare_bearer": "sent bearer {s}",
    "basic_auth": "Proxy-Authorization: Basic {s}",
    "json_password": '{{"password": "{s}"}}',
    "json_client_secret": '{{"client_secret": "{s}", "id": 1}}',
    "env_style": "PGPASSWORD={s} psql",
    "url_userinfo": "https://user:{s}@example.com/x",
    "url_user_only": "https://{s}@example.com/x",
    "url_query_token": "https://example.com/cb?access_token={s}&x=1",
    "stdin_payload": "stdin='{s}'",
    "exception_repr": "RuntimeError('auth failed for secret {s}')",
    "pem_block": pem("BEGIN", "OPENSSH ") + "\n{s}\n" + pem("END", "OPENSSH "),
    "pem_unterminated": pem("BEGIN", "RSA ") + "\n{s}",
    "embedded_newline": "ok\npassword: {s}",
}  # fmt: skip
VENDOR_TOKENS = {
    "openai": "sk-" + "proj-" + "A1b2C3d4E5f6G7h8I9j0",
    "github": "gh" + "p_" + "aB3dE5gH7jK9mN1pQ3sT5vX7z",
    "aws_access_key": "AK" + "IA" + "Q3EXAMPLE7KEY2AB",
    "aws_secret": "wJalrXUtnFEMI" + "/K7MDENG/bPxRfiCYEXAMPLEKEY",
    "slack": "xo" + "xb-" + "1234567890-abcdefghij",
    "jwt": "eyJ" + "hbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJlLXZhbHVl",
    "long_hex": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
}  # fmt: skip


def written_blob(root: Path) -> bytes:
    return b"".join(p.read_bytes() for p in (root / SERVICE).iterdir() if p.is_file())


def write_through_rotation_and_crash(root: Path, message: str, literals=()) -> float:
    """Persist one message in a rotated, a crashed and a recovered epoch."""
    first = start(root, redact_values=literals)
    first.write(message)
    first.rotate()
    first.write(message)
    first.sync()
    first._release()  # crash without close
    recovered = start(root, redact_values=literals)
    manifest = load_manifest(root / SERVICE, SERVICE)
    assert manifest is not None
    since = manifest.entries[-1].started_at
    recovered.write(message)
    recovered.close()
    return since


@pytest.mark.parametrize("sentinel", [REVIEWER_SENTINEL, PLAIN_SENTINEL])
@pytest.mark.parametrize("shape", sorted(SECRET_SHAPES))
def test_secret_shapes_never_reach_disk(root, source, shape, sentinel):
    message = SECRET_SHAPES[shape].format(s=sentinel)
    since = write_through_rotation_and_crash(root, message)
    assert sentinel.encode() not in written_blob(root)
    assert sentinel not in source.read_window([SERVICE], since)
    words, _, _ = drain(source)
    assert len(words) == 3 and not any(sentinel in word for word in words)
    assert all("[redacted]" in word for word in words)


@pytest.mark.parametrize("name", sorted(VENDOR_TOKENS))
def test_vendor_and_high_entropy_tokens_never_reach_disk(root, source, name):
    token = VENDOR_TOKENS[name]
    write_through_rotation_and_crash(root, f"loaded credential {token} ok")
    assert token.encode() not in written_blob(root)
    for fragment in (token[:12], token[-12:]):
        assert fragment.encode() not in written_blob(root)


def test_registered_literal_is_redacted_in_any_case(root, source):
    literal = "Literal-" + "Reg-Secret"
    write_through_rotation_and_crash(
        root, f"a {literal} b {literal.lower()} c {literal.upper()}", [literal]
    )
    blob = written_blob(root).lower()
    assert literal.lower().encode() not in blob


def test_benign_records_survive_redaction():
    keep = [
        "job 012345abcdef exited 0 after 1.5s", "started worker pid=4242 port=8000",
        "bulk-0001-" + "x" * 30, "ls --color=auto /var/tmp",
    ]  # fmt: skip
    assert [log_source.redact_log_text(text) for text in keep] == keep


def test_structured_events_persist_only_allowlisted_scalars(root, source):
    writer = start(root, clock=Clock())
    writer.write_event(
        "job_exit", job="012345abcdef", code=0, ok=True, ratio=0.5, missing=None,
        argv=["mysql", "-p" + PLAIN_SENTINEL], note=f"free text {PLAIN_SENTINEL}",
        nan=float("nan"),
    )  # fmt: skip
    for bad in ({"event": "bad name"}, {"event": "ok", "../x": 1}):
        event = bad.pop("event")
        with pytest.raises(ValueError, match="identifiers"):
            writer.write_event(event, **bad)
    writer.close()
    expected = "job_exit job=012345abcdef code=0 ok=true ratio=0.5 missing=null"
    redacted = " argv=[redacted] note=[redacted] nan=[redacted]"
    assert texts(read(source).data) == [expected + redacted]
    assert PLAIN_SENTINEL.encode() not in written_blob(root)


def test_redaction_stays_linear_on_adversarial_records():
    """A quadratic rule took ~100 s on one 64 KiB word; this bound is generous."""
    unit = 64 << 10
    hostile = [
        "a" * unit, "pass" * (unit // 4) + "=v", "x-" + "pass" * (unit // 4) + ":",
        "--" + "pass" * (unit // 4), "a." * (unit // 2), "-a" * (unit // 2),
        '"' + "token" * (unit // 5) + '"', "a+" * (unit // 2) + "://",
    ]  # fmt: skip
    started = time.perf_counter()
    for text in hostile:
        log_source.redact_log_text(text)
    assert time.perf_counter() - started < 10.0
