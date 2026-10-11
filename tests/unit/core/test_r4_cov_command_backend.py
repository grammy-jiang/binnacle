"""Linux-runnable coverage for the R4 manager-backed command backend seams."""

import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from binnacle.features.commands import command_backend as cb
from binnacle.features.commands.command_backend import (
    DARWIN_MANAGER_REVIEW_PENDING,
    DARWIN_MANAGER_UNAVAILABLE_NOTE,
    DARWIN_OWNER_LOST_NOTE,
    RESOURCES_SAMPLED,
    DarwinManagerCommandBackend,
    ManagerBindings,
)
from binnacle.features.commands.command_contracts import (
    CommandFailure,
    CommandReply,
    RestrictedCommandBackend,
)

AVAILABLE = {
    "run_command": "AVAILABLE",
    "job_status": "AVAILABLE",
    "stop_job": "AVAILABLE",
}


class FakeStore:
    def read_meta(self, jobs_dir, job_id):
        path = Path(jobs_dir) / job_id / "meta.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def read_log(self, jobs_dir, job_id):
        return (Path(jobs_dir) / job_id / "out.log").read_bytes()

    def read_log_range(self, jobs_dir, job_id, start, max_bytes):
        data = self.read_log(jobs_dir, job_id)
        return data[start : start + max_bytes], len(data)

    def list_job_ids(self, jobs_dir):
        return sorted(p.name for p in Path(jobs_dir).iterdir())


class ManagerError(RuntimeError):
    """Mirrors DarwinJobManagerError: the composed DarwinJobClient() error."""


class FakeClient:
    def __init__(self, backend_dir, start_reply=None, *, reachable=True):
        self.calls = []
        self.pings = 0
        self.start_reply = start_reply or {"job_id": "j1", "state": "running"}
        self.backend_dir = backend_dir
        self.reachable = reachable

    def _require_reachable(self):
        if not self.reachable:
            raise ManagerError("job manager unavailable: connection refused")

    def ping(self, socket_path):
        # J2 frozen ping reply fields (job_manager_service.dispatch "ping").
        self.pings += 1
        self._require_reachable()
        return {
            "ok": True,
            "version": 1,
            "owner_instance_id": "owner-1",
            "boot_id": "boot-1",
            "pid": 999,
            "package_version": "0.0.0",
            "running_jobs": 0,
            "unknown_jobs": 0,
            "revision": "0" * 40,
        }

    def start(self, socket_path, **kwargs):
        self.calls.append(("start", socket_path, kwargs))
        return self.start_reply

    def stop(self, socket_path, job_id, *, call_id):
        self._require_reachable()
        self.calls.append(("stop", socket_path, job_id, call_id))
        write_meta(self.backend_dir, job_id, exit_code=None, signal=15)


def write_meta(jobs_dir, job_id, **fields):
    meta_path = Path(jobs_dir) / job_id / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    meta.setdefault("command", "echo hi")
    meta.setdefault("workdir", "/tmp")
    meta.setdefault("pid", 4242)
    meta.setdefault("started_at", 1000.0)
    meta.update(fields)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta))
    return meta_path


def make_backend(tmp_path, *, socket_path=None, release_states=None, client=None):
    checked = []
    bindings = ManagerBindings(
        store=FakeStore(),
        call_id=lambda: "call-1",
        check_partial=checked.append,
        owner_lost_refusal="owner lost refusal",
        unavailable="job manager unavailable",
    )
    backend = DarwinManagerCommandBackend(
        jobs_dir=tmp_path,
        socket_path=socket_path if socket_path is not None else tmp_path / "s.sock",
        release_states=AVAILABLE if release_states is None else release_states,
        warmup_s=0.25,
        max_output_chars=1000,
        client=client if client is not None else FakeClient(tmp_path),
        bindings=bindings,
    )
    return backend, checked


def test_socket_path_static_and_resolved(tmp_path):
    backend, _ = make_backend(tmp_path, socket_path=str(tmp_path / "x.sock"))
    assert backend.socket_path == tmp_path / "x.sock"
    backend, _ = make_backend(tmp_path, socket_path=lambda: tmp_path / "y.sock")
    assert backend.socket_path == tmp_path / "y.sock"


@pytest.mark.parametrize(
    "exc,code",
    [(OSError("no dir"), "OSError"), (RuntimeError("no runtime"), "RuntimeError")],
)
def test_socket_path_resolver_failure_is_unavailable(tmp_path, exc, code):
    def resolver():
        raise exc

    backend, _ = make_backend(tmp_path, socket_path=resolver)
    with pytest.raises(CommandFailure, match=f"job manager unavailable: {code}"):
        _ = backend.socket_path


def test_socket_path_resolver_failure_uses_error_code(tmp_path):
    exc = RuntimeError("runtime")
    exc.code = "runtime_dir_missing"

    def resolver():
        raise exc

    backend, _ = make_backend(tmp_path, socket_path=resolver)
    with pytest.raises(CommandFailure, match="unavailable: runtime_dir_missing"):
        _ = backend.socket_path


def test_require_available_uses_committed_rows(tmp_path):
    backend, _ = make_backend(tmp_path)
    backend.require_available()
    backend, _ = make_backend(
        tmp_path, release_states={**AVAILABLE, "stop_job": "UNAVAILABLE"}
    )
    with pytest.raises(CommandFailure) as caught:
        backend.require_available()
    assert str(caught.value) == DARWIN_MANAGER_REVIEW_PENDING


def test_start_running_returns_without_waiting(tmp_path):
    client = FakeClient(tmp_path)
    backend, _ = make_backend(tmp_path, client=client)
    assert backend.start_and_wait("echo hi", tmp_path, None, 1.5) == "j1"
    kind, sock, kwargs = client.calls[0]
    assert kind == "start" and sock == tmp_path / "s.sock"
    assert kwargs == {
        "command": "echo hi",
        "workdir": tmp_path,
        "stdin": None,
        "wait_seconds": 1.5,
        "call_id": "call-1",
    }


def test_start_not_running_waits_for_spool_record(tmp_path, monkeypatch):
    client = FakeClient(tmp_path, start_reply={"job_id": 7, "state": "exited"})
    backend, _ = make_backend(tmp_path, client=client)
    waited = []
    monkeypatch.setattr(
        backend, "await_exit", lambda job_id, timeout: waited.append((job_id, timeout))
    )
    assert backend.start_and_wait("true", tmp_path, "in", 0.0) == "7"
    assert waited == [("7", cb.EXIT_RECORD_GRACE_S)]


def test_job_state_absent_and_reserved(tmp_path):
    backend, _ = make_backend(tmp_path)
    assert backend.job_state("missing") is None
    write_meta(tmp_path, "reserved", pid=None)
    assert backend.job_state("reserved") is None


def test_job_state_running_without_log(tmp_path):
    write_meta(tmp_path, "j1")
    backend, _ = make_backend(tmp_path)
    state = backend.job_state("j1")
    assert state["state"] == "running"
    assert state["log_bytes"] == 0 and state["last_output_age_s"] is None
    assert state["pgid"] == 4242 and state["cgroup"] is None
    assert "note" not in state


def test_job_state_unreachable_manager_is_unverified(tmp_path):
    # SD-41: only the manager can verify a non-terminal record.
    write_meta(tmp_path, "j1")
    backend, _ = make_backend(tmp_path, client=FakeClient(tmp_path, reachable=False))
    state = backend.job_state("j1")
    assert state["state"] == "unknown"
    assert state["note"] == DARWIN_MANAGER_UNAVAILABLE_NOTE


def test_job_state_unreachable_manager_keeps_terminal_record(tmp_path):
    write_meta(tmp_path, "j1", exit_code=2)
    client = FakeClient(tmp_path, reachable=False)
    backend, _ = make_backend(tmp_path, client=client)
    state = backend.job_state("j1")
    assert state["state"] == "exited" and "note" not in state
    assert client.pings == 0


def test_stop_job_unreachable_manager_fails_the_stop(tmp_path):
    write_meta(tmp_path, "live")
    client = FakeClient(tmp_path, reachable=False)
    backend, _ = make_backend(tmp_path, client=client)
    with pytest.raises(ManagerError, match="job manager unavailable"):
        backend.stop_job("live")
    assert client.calls == []


def test_job_state_exited_with_log(tmp_path):
    write_meta(tmp_path, "j1", exit_code=0, ended_at=1002.5, pgid=11)
    (tmp_path / "j1" / "out.log").write_bytes(b"hello")
    backend, _ = make_backend(tmp_path)
    state = backend.job_state("j1")
    assert state["state"] == "exited" and state["exit_code"] == 0
    assert state["runtime_s"] == 2.5 and state["pgid"] == 11
    assert state["log_bytes"] == 5 and state["last_output_age_s"] is not None


def test_job_state_signal_only_is_exited(tmp_path):
    write_meta(tmp_path, "j1", signal=9)
    backend, _ = make_backend(tmp_path)
    assert backend.job_state("j1")["state"] == "exited"


def test_job_state_unknown_authority_is_never_exited(tmp_path):
    write_meta(tmp_path, "j1", authority="UNKNOWN", exit_code=1)
    backend, _ = make_backend(tmp_path)
    state = backend.job_state("j1")
    assert state["state"] == "unknown"
    assert state["note"] == DARWIN_OWNER_LOST_NOTE


def test_stop_job_paths(tmp_path):
    client = FakeClient(tmp_path)
    backend, checked = make_backend(tmp_path, client=client)
    assert backend.stop_job("missing") is None

    write_meta(tmp_path, "lost", authority="UNKNOWN")
    with pytest.raises(CommandFailure, match="owner lost refusal"):
        backend.stop_job("lost")

    write_meta(tmp_path, "done", exit_code=0)
    assert backend.stop_job("done")["state"] == "exited"
    assert client.calls == []

    write_meta(tmp_path, "live")
    stopped = backend.stop_job("live")
    assert stopped["state"] == "exited" and stopped["signal"] == 15
    assert client.calls == [("stop", tmp_path / "s.sock", "live", "call-1")]
    assert [m["command"] for m in checked] == ["echo hi"] * 2


def test_stop_job_reserved_record_returns_none(tmp_path):
    write_meta(tmp_path, "reserved", pid=None)
    backend, checked = make_backend(tmp_path)
    assert backend.stop_job("reserved") is None
    assert len(checked) == 1


def test_list_jobs_sorted_newest_first_and_skips_reserved(tmp_path):
    write_meta(tmp_path, "old", started_at=10.0, exit_code=0, ended_at=11.0)
    write_meta(tmp_path, "new", started_at=20.0, exit_code=0, ended_at=21.0)
    write_meta(tmp_path, "reserved", pid=None)
    backend, _ = make_backend(tmp_path)
    assert [s["job_id"] for s in backend.list_jobs()] == ["new", "old"]


def test_list_jobs_pings_at_most_once(tmp_path):
    write_meta(tmp_path, "a", started_at=10.0)
    write_meta(tmp_path, "b", started_at=20.0)
    write_meta(tmp_path, "c", started_at=30.0, exit_code=0)
    client = FakeClient(tmp_path, reachable=False)
    backend, _ = make_backend(tmp_path, client=client)
    states = backend.list_jobs()
    assert [(s["job_id"], s["state"]) for s in states] == [
        ("c", "exited"),
        ("b", "unknown"),
        ("a", "unknown"),
    ]
    assert client.pings == 1


def test_await_exit_returns_terminal_absent_or_on_deadline(tmp_path, monkeypatch):
    backend, _ = make_backend(tmp_path)
    assert backend.await_exit("missing", 1.0) is None
    write_meta(tmp_path, "done", exit_code=3)
    assert backend.await_exit("done", 1.0)["exit_code"] == 3
    write_meta(tmp_path, "live")
    assert backend.await_exit("live", 0.0)["state"] == "running"

    sleeps = []

    def fake_sleep(seconds):
        sleeps.append(seconds)
        write_meta(tmp_path, "live", exit_code=0)

    monkeypatch.setattr(cb.time, "sleep", fake_sleep)
    assert backend.await_exit("live", 60.0)["state"] == "exited"
    assert sleeps == [0.05]


def test_logs_and_processes_use_store_only(tmp_path):
    write_meta(tmp_path, "j1")
    (tmp_path / "j1" / "out.log").write_bytes(b"abcdef")
    backend, _ = make_backend(tmp_path)
    assert backend.read_log("j1") == b"abcdef"
    assert backend.read_log_range("j1", 2, 3) == (b"cde", 6)
    assert backend.job_processes("j1") == []
    assert backend.job_processes("j1", 10) == []


class ProcessesClient(FakeClient):
    def __init__(self, backend_dir, reply=None, exc=None):
        super().__init__(backend_dir)
        self.reply, self.exc = reply, exc

    def processes(self, socket_path, job_id, *, max_cmd_chars):
        self.calls.append(("processes", socket_path, job_id, max_cmd_chars))
        if self.exc is not None:
            raise self.exc
        return self.reply


def test_job_processes_from_manager_group(tmp_path):
    # JCRP-F6: the manager lists its own verified group; the MCP never reads pids.
    listing = [{"pid": 4242, "ppid": 1, "state": "S", "cmd": "sleep 30"}]
    client = ProcessesClient(tmp_path, reply={"processes": listing})
    backend, _ = make_backend(tmp_path, client=client)
    assert backend.job_processes("j1", 50) == listing
    assert client.calls == [("processes", tmp_path / "s.sock", "j1", 50)]


@pytest.mark.parametrize(
    "reply,exc",
    [
        ({"processes": "not a list"}, None),
        ({}, None),
        (None, OSError("refused")),
        (None, RuntimeError("bad reply")),
        (None, CommandFailure("job manager unavailable")),
    ],
)
def test_job_processes_unavailable_is_empty(tmp_path, reply, exc):
    client = ProcessesClient(tmp_path, reply=reply, exc=exc)
    backend, _ = make_backend(tmp_path, client=client)
    assert backend.job_processes("j1") == []


def test_disclose_status(tmp_path):
    backend, _ = make_backend(tmp_path)
    reply = CommandReply("Job j1.", {"job_id": "j1"})
    assert backend.disclose_status("missing", reply) is reply

    write_meta(tmp_path, "plain", exit_code=0)
    plain = backend.disclose_status("plain", reply)
    assert plain.summary == "Job j1." and plain.payload == {"job_id": "j1"}

    write_meta(tmp_path, "lost", authority="UNKNOWN", resource_usage={"cpu_s": 1.0})
    lost = backend.disclose_status("lost", reply)
    assert lost.payload["note"] == DARWIN_OWNER_LOST_NOTE
    assert lost.payload["resource_usage"] == {
        "cpu_s": 1.0,
        "accounting": RESOURCES_SAMPLED,
    }
    assert lost.payload["state"] == "unknown"
    # RJ4-F1: the owner-lost text replaces the Linux summary.
    assert lost.summary == (
        f"Job lost state unknown: {DARWIN_OWNER_LOST_NOTE}. "
        f"Resource usage is {RESOURCES_SAMPLED}."
    )
    assert reply.payload == {"job_id": "j1"}


def test_disclose_status_unknown_payload_is_unverified(tmp_path):
    # SD-41: an "unknown" payload without a spool note is rendered unverified.
    write_meta(tmp_path, "j1", exit_code=0)
    backend, _ = make_backend(tmp_path)
    reply = CommandReply("Job j1 is gone.", {"job_id": "j1", "state": "unknown"})
    disclosed = backend.disclose_status("j1", reply)
    assert (
        disclosed.summary == f"Job j1 state unknown: {DARWIN_MANAGER_UNAVAILABLE_NOTE}."
    )
    assert disclosed.payload == {
        "job_id": "j1",
        "state": "unknown",
        "note": DARWIN_MANAGER_UNAVAILABLE_NOTE,
    }


def test_disclose_status_unreachable_manager(tmp_path):
    write_meta(tmp_path, "j1")
    client = FakeClient(tmp_path, reachable=False)
    backend, _ = make_backend(tmp_path, client=client)
    reply = CommandReply("Job j1 running.", {"job_id": "j1", "state": "running"})
    disclosed = backend.disclose_status("j1", reply)
    assert disclosed.payload["state"] == "unknown"
    assert disclosed.payload["note"] == DARWIN_MANAGER_UNAVAILABLE_NOTE
    assert (
        disclosed.summary == f"Job j1 state unknown: {DARWIN_MANAGER_UNAVAILABLE_NOTE}."
    )


def test_backend_attributes(tmp_path):
    backend, _ = make_backend(tmp_path)
    assert backend.owner_mode == "manager"
    assert backend.warmup_s == 0.25 and backend.max_output_chars == 1000
    assert backend.jobs_dir == tmp_path


@pytest.fixture
def restore_native_config():
    states, factory = cb._native_release_states, cb._native_backend_factory
    yield
    cb._native_release_states, cb._native_backend_factory = states, factory


def test_configure_native_release_states(restore_native_config):
    states = {"run_command": "AVAILABLE"}
    cb.configure_native_release_states(states)
    states["run_command"] = "changed"
    assert cb._native_release_states == {"run_command": "AVAILABLE"}
    cb.configure_native_release_states(None)
    assert cb._native_release_states is None


def test_create_backend_non_linux_uses_factory_or_restricted(
    restore_native_config, monkeypatch
):
    monkeypatch.setattr(cb.platform, "system", lambda: "Darwin")
    sentinel = object()
    cb.configure_native_command_backend(lambda: sentinel)
    assert cb.create_command_backend() is sentinel
    cb.configure_native_command_backend(None)
    cb.configure_native_release_states(AVAILABLE)
    assert isinstance(cb.create_command_backend(), RestrictedCommandBackend)


def test_create_backend_linux_is_durable(monkeypatch):
    imported = []
    monkeypatch.setattr(cb.platform, "system", lambda: "Linux")
    monkeypatch.setattr(cb, "import_module", imported.append)
    assert isinstance(cb.create_command_backend(), cb.DurableCommandBackend)
    assert imported == [
        "binnacle.features.commands.jobs",
        "binnacle.features.commands.job_owner",
    ]


def test_durable_backend_engine_settings(monkeypatch):
    import binnacle.features.commands as commands_pkg

    fake = ModuleType("binnacle.features.commands.jobs")
    fake.OWNER_MODE, fake.WARMUP_S, fake.RUN_MAX_OUTPUT_CHARS = "embedded", 0.5, 77
    monkeypatch.setitem(sys.modules, "binnacle.features.commands.jobs", fake)
    monkeypatch.setattr(commands_pkg, "jobs", fake, raising=False)
    backend = cb.DurableCommandBackend()
    assert backend.owner_mode == "embedded"
    assert backend.warmup_s == 0.5
    assert backend.max_output_chars == 77
