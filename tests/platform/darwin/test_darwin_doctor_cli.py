"""Darwin doctor and J7m-W3 admission checks; no production mutations."""

from __future__ import annotations

import json
import os
import plistlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from binnacle.diagnostics import darwin_doctor as native
from binnacle.diagnostics import doctor as linux_checks
from binnacle.doctor_contracts import ok
from scripts.mac_w3_deploy_gate import parse_startup_doctor


def fixtures(tmp_path: Path, **fields: object) -> Path:
    for service in native._LAUNCHD_SERVICES:
        label = f"com.binnacle.{service}"
        plist = {
            "Label": label,
            "ProgramArguments": ["/bin/sh", "-c", "echo secret-never-print-me"],
            "RunAtLoad": True,
            "KeepAlive": True,
            "Umask": 0o077,
        }
        plist.update(fields)
        path = tmp_path / f"{label}.plist"
        path.write_bytes(plistlib.dumps(plist))
        path.chmod(0o644)
    return tmp_path


def running(_label: str):
    return "\tstate = running\n\tpid = 1007\n"


def test_valid_launchd_plists_and_matching_live_services(tmp_path):
    root = fixtures(tmp_path)
    rows, pids = native.check_launchd(root, expected_uid=os.getuid(), status=running)
    assert len(rows) == 10
    assert all(r.status == "ok" for r in rows)
    assert pids == dict.fromkeys(native._LAUNCHD_SERVICES, 1007)
    assert all("secret-never-print-me" not in r.detail for r in rows)


@pytest.mark.parametrize(
    "change",
    [
        {"RunAtLoad": False},
        {"KeepAlive": False},
        {"Umask": 0o022},
        {"ProgramArguments": []},
        {"ProgramArguments": ["python3"]},
        {"ProgramArguments": ["/unlikely/this-does-not-exist"]},
        {"Label": "com.wrong.service"},
    ],
)
def test_missing_boot_safety_properties_never_pass(tmp_path, change):
    root = fixtures(tmp_path, **change)
    rows, pids = native.check_launchd(root, expected_uid=os.getuid(), status=running)
    assert all(r.status == "fail" for r in rows[::2])
    assert len(pids) == 5


@pytest.mark.parametrize(
    "kind", ["symlink", "hardlink", "public", "corrupt", "missing"]
)
def test_launchd_refuses_untrusted_service_definitions(tmp_path, kind):
    root = fixtures(tmp_path)
    file = root / "com.binnacle.jobs.plist"
    if kind == "symlink":
        payload = root / "payload.plist"
        file.rename(payload)
        file.symlink_to(payload)
    elif kind == "hardlink":
        os.link(file, root / "extra.link")
    elif kind == "public":
        file.chmod(0o666)
    elif kind == "corrupt":
        file.write_text("not a plist")
    else:
        file.unlink()
    rows, _ = native.check_launchd(root, expected_uid=os.getuid(), status=running)
    assert rows[2].group == "launchd" and rows[2].status == "fail"


def test_launchd_refuses_wrong_owner_or_unavailable_status(tmp_path):
    root = fixtures(tmp_path)
    rows, _ = native.check_launchd(root, expected_uid=-1, status=running)
    assert all(row.status == "fail" for row in rows[::2])
    rows, pids = native.check_launchd(
        root, expected_uid=os.getuid(), status=lambda label: None
    )
    assert all(row.status == "fail" for row in rows[1::2])
    assert pids == {}


@pytest.mark.parametrize(
    "output",
    [
        "\tstate = waiting\n\tpid = 77\n",
        "\tstate = running\n",
        "\tstate = running\n\tpid = 0\n",
        "\tstate = running\n\tpid = xyz\n",
        None,
    ],
)
def test_launchd_fails_closed_on_unverified_pid_or_state(tmp_path, output):
    root = fixtures(tmp_path)
    rows, pids = native.check_launchd(
        root, expected_uid=os.getuid(), status=lambda label: output
    )
    assert not pids
    assert all(row.status == "fail" for row in rows[1::2])


def fake_manager(tmp_path, monkeypatch):
    monkeypatch.setattr(
        native,
        "get_settings",
        lambda: SimpleNamespace(jobs=SimpleNamespace(socket_path=None, dir=tmp_path)),
    )
    socket = tmp_path / "jobs.sock"
    monkeypatch.setattr(
        native, "create_runtime_paths", lambda: SimpleNamespace(jobs_socket=socket)
    )
    reply = {
        "ok": True,
        "pid": 1007,
        "revision": "a" * 12,
        "jobs_dir": str(tmp_path),
        "running_jobs": 0,
        "unknown_jobs": 0,
    }
    return reply, socket


def test_manager_authenticated_identity_and_revision(tmp_path, monkeypatch):
    reply, socket = fake_manager(tmp_path, monkeypatch)
    seen = []
    checks = native.check_native_job_manager(
        "a" * 40,
        {"jobs": 1007},
        ping=lambda path: seen.append(path) or reply,
    )
    assert seen == [socket]
    assert checks == [
        ok(
            "jobs-service",
            "authenticated pid=1007 revision=aaaaaaaaaaaa; 0 running, 0 unknown",
        )
    ]


@pytest.mark.parametrize(
    "change",
    [
        {"ok": False},
        {"pid": 2000},
        {"pid": True},
        {"revision": "unknown"},
        {"jobs_dir": "/wrong/directory"},
        {"running_jobs": -1},
        {"unknown_jobs": True},
        {"running_jobs": None},
    ],
)
def test_manager_fails_closed_on_unverified_rpc(tmp_path, monkeypatch, change):
    reply, _ = fake_manager(tmp_path, monkeypatch)
    reply.update(change)
    rows = native.check_native_job_manager(
        "a" * 12, {"jobs": 1007}, ping=lambda _: reply
    )
    assert len(rows) == 1
    assert rows[0].group == "jobs-service"
    assert rows[0].status == "fail"


def test_manager_refuses_missing_unit_and_ipc_error(tmp_path, monkeypatch):
    fake_manager(tmp_path, monkeypatch)
    missing = native.check_native_job_manager("a" * 12, {})
    assert missing[0].status == "fail"

    def unavailable(_path):
        raise RuntimeError("cannot read a private key: do not leak this")

    rows = native.check_native_job_manager("a" * 12, {"jobs": 1007}, ping=unavailable)
    assert rows[0].status == "fail"
    assert "private key" not in rows[0].detail


def test_manager_stale_checkout_revision_is_fail(tmp_path, monkeypatch):
    reply, _ = fake_manager(tmp_path, monkeypatch)
    rows = native.check_native_job_manager(
        "b" * 12, {"jobs": 1007}, ping=lambda _: reply
    )
    assert [x.status for x in rows] == ["ok", "fail"]


def test_manager_unknown_jobs_and_python_capability_fail(tmp_path, monkeypatch):
    reply, _ = fake_manager(tmp_path, monkeypatch)
    reply.update(
        {
            "unknown_jobs": 1,
            "manager_python_version": "3.12",
            "manager_waitid_available": False,
        }
    )
    rows = native.check_native_job_manager(
        "a" * 12, {"jobs": 1007}, ping=lambda _: reply
    )
    assert [x.status for x in rows] == ["ok", "warn", "fail"]
    assert rows[2].group == "jobs-python"


def test_manager_reports_actual_313_runtime(tmp_path, monkeypatch):
    reply, _ = fake_manager(tmp_path, monkeypatch)
    reply["manager_python_version"] = "3.13"
    reply["manager_waitid_available"] = True
    rows = native.check_native_job_manager(
        "a" * 12, {"jobs": 1007}, ping=lambda _: reply
    )
    assert [x.status for x in rows] == ["ok", "ok"]
    assert rows[-1].group == "jobs-python"


def test_valid_but_wrong_plist_top_level_is_not_accepted(tmp_path):
    root = fixtures(tmp_path)
    (root / "com.binnacle.jobs.plist").write_bytes(plistlib.dumps([1, 2, 3]))
    rows, _ = native.check_launchd(root, expected_uid=os.getuid(), status=running)
    assert rows[2].status == "fail"


def test_launchd_runtime_probe_exception_fails_closed(tmp_path):
    root = fixtures(tmp_path)

    def unreachable(_label):
        raise OSError("launchd unavailable")

    rows, pids = native.check_launchd(
        root, expected_uid=os.getuid(), status=unreachable
    )
    assert pids == {}
    assert all(row.status == "fail" for row in rows[1::2])


def test_unverifiable_checkout_revision_fails_darwin_doctor(tmp_path, monkeypatch):
    reply, _ = fake_manager(tmp_path, monkeypatch)
    rows = native.check_native_job_manager(
        "unknown", {"jobs": 1007}, ping=lambda _: reply
    )
    assert [x.status for x in rows] == ["ok", "fail"]
    assert "checkout" in rows[-1].detail


@pytest.mark.parametrize("version", ["not-a-number", "3.13.0", None])
def test_unparseable_manager_python_capability_is_fail(tmp_path, monkeypatch, version):
    reply, _ = fake_manager(tmp_path, monkeypatch)
    reply["manager_python_version"] = version
    reply["manager_waitid_available"] = False
    rows = native.check_native_job_manager(
        "a" * 12, {"jobs": 1007}, ping=lambda _: reply
    )
    assert rows[-1].status == "fail"
    assert rows[-1].group == "jobs-python"


@pytest.mark.parametrize("fake_result", ["not-a-list", ["not-a-check"]])
def test_malformed_checks_are_diagnostic_fail_not_uncaught_exception(fake_result):
    checks = []
    native._append_safe(checks, "startup", lambda: fake_result)
    assert len(checks) == 1
    assert checks[0].group == "startup"
    assert checks[0].status == "fail"
    assert parse_startup_doctor(linux_checks.render_json(checks)[0])[0] is False


def test_unexpected_launchd_error_keeps_a_valid_json_report(monkeypatch):
    monkeypatch.setattr(
        linux_checks, "check_startup_imports", lambda: [ok("startup", "clean")]
    )
    monkeypatch.setattr(linux_checks, "check_provenance", list)
    monkeypatch.setattr(linux_checks, "check_config", list)
    monkeypatch.setattr(linux_checks, "check_config_keys", list)
    monkeypatch.setattr(linux_checks, "check_rg_version", lambda _: [])
    monkeypatch.setattr(linux_checks, "check_token", lambda _: [])
    monkeypatch.setattr(linux_checks, "check_endpoint", lambda *_: [])
    monkeypatch.setattr(
        native,
        "check_launchd",
        lambda: (_ for _ in ()).throw(RuntimeError("unavailable launchd")),
    )
    monkeypatch.setattr(native, "check_native_job_manager", lambda *a: [])
    monkeypatch.setattr(native, "get_settings", lambda: SimpleNamespace(rg_bin="rg"))
    monkeypatch.setattr(
        native, "runtime_provenance", lambda: SimpleNamespace(revision="a" * 12)
    )
    rendered, code = linux_checks.render_json(
        native.run_all(server_url="http://127.0.0.1/mcp", token_file=Path("/none"))
    )
    assert code == 1
    body = json.loads(rendered)
    assert any(
        x["group"] == "launchd" and x["status"] == "fail" for x in body["checks"]
    )
    assert parse_startup_doctor(rendered)[:2] == (True, "startup_ok")


def test_unavailable_startup_checker_is_a_blocking_gate_failure(monkeypatch):
    monkeypatch.setattr(
        linux_checks,
        "check_startup_imports",
        lambda: (_ for _ in ()).throw(OSError("unreadable record")),
    )
    rows = []
    native._append_safe(rows, "startup", linux_checks.check_startup_imports)
    body, rc = linux_checks.render_json(rows)
    assert rc == 1
    assert parse_startup_doctor(body)[:2] == (False, "startup_failure")
    assert "unreadable record" not in body
