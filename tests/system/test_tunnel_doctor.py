"""The tunnel companion's diagnostics: the quiet gate and the composition."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from binnacle import doctor, tunnel_doctor, units


def log_with(path: Path, stamps: list[str]) -> Path:
    lines = [
        json.dumps(
            {
                "time": s,
                "level": "INFO",
                "msg": "dispatcher forwarded command to MCP server",
            }
        )
        for s in stamps
    ]
    path.write_text("\n".join(lines) + "\n")
    return path


def test_parse_time_handles_go_nanoseconds_naive_and_bad_input():
    when = tunnel_doctor.parse_time("2026-09-20T23:31:30.909439218+10:00")
    assert when is not None and when.isoformat() == "2026-09-20T23:31:30.909439+10:00"
    zulu = tunnel_doctor.parse_time("2026-09-20T13:31:30Z")
    assert zulu is not None and zulu.utcoffset() == timedelta(0)
    naive = tunnel_doctor.parse_time("2026-09-20T13:31:30")
    assert naive is not None and naive.tzinfo == timezone.utc
    assert tunnel_doctor.parse_time("yesterday") is None


def test_busy_when_the_tunnel_forwarded_a_command_recently(tmp_path):
    now = datetime(2026, 9, 20, 13, 0, 0, tzinfo=timezone.utc)
    log = log_with(tmp_path / "tunnel.log", [(now - timedelta(seconds=5)).isoformat()])
    reasons = tunnel_doctor.tunnel_busy_reasons(
        30, log, fetch=lambda u, s: "", now=lambda: now
    )
    assert reasons == [
        "the tunnel forwarded a command 5 s ago; a restart drops its reply"
    ]

    log_with(log, [(now - timedelta(seconds=90)).isoformat()])
    quiet = tunnel_doctor.tunnel_busy_reasons(
        30, log, fetch=lambda u, s: "", now=lambda: now
    )
    assert quiet == []


def test_busy_when_the_server_saw_calls_and_when_the_journal_is_unreadable(tmp_path):
    reasons = tunnel_doctor.tunnel_busy_reasons(
        30, None, fetch=lambda u, s: "event=tool_call\nevent=tool_call\n"
    )
    assert reasons == ["2 tool call(s) on the server in the last 30 s"]

    def boom(unit: str, since: str) -> str:
        raise OSError("no journal")

    reasons = tunnel_doctor.tunnel_busy_reasons(
        30, tmp_path / "missing.log", fetch=boom
    )
    assert len(reasons) == 1 and "journal unreadable" in reasons[0]


def test_read_profile_and_log_file(tmp_path):
    p = tmp_path / "p.yaml"
    assert tunnel_doctor.read_profile(p) == {}
    p.write_text("nope")
    assert tunnel_doctor.read_profile(p) == {}
    p.write_text(json.dumps(["not", "a", "dict"]))
    assert tunnel_doctor.read_profile(p) == {}
    p.write_text(json.dumps({"log": {"file": "/var/log/t.log"}}))
    assert tunnel_doctor.log_file_of(tunnel_doctor.read_profile(p)) == Path(
        "/var/log/t.log"
    )
    assert tunnel_doctor.log_file_of({}) is None
    assert tunnel_doctor.log_file_of({"log": "x"}) is None


def test_run_all_composes_unit_config_and_poller_checks(tmp_path, monkeypatch):
    settings = SimpleNamespace(
        auth=SimpleNamespace(token_file=tmp_path / "token"),
        serve=SimpleNamespace(host="127.0.0.1", port=8123),
    )
    monkeypatch.setattr(tunnel_doctor, "get_settings", lambda: settings)
    pdir = tmp_path / "profile"
    pdir.mkdir()
    (pdir / "binnacle.yaml").write_text(
        json.dumps({"log": {"file": str(tmp_path / "t.log")}})
    )
    monkeypatch.setattr(
        tunnel_doctor,
        "profile_config",
        lambda profile="binnacle": pdir / f"{profile}.yaml",
    )
    monkeypatch.setattr(units, "UNIT_DIR", tmp_path / "units")
    calls = []
    monkeypatch.setattr(
        units,
        "check_unit_drift",
        lambda path, owner, render, group, hint: (
            calls.append(("drift", path.name, owner)) or [doctor.ok("tunnel", "drift")]
        ),
    )
    monkeypatch.setattr(
        units,
        "check_unit_process",
        lambda unit, group, s, r: (
            calls.append(("process", unit)) or [doctor.ok("tunnel", "process")]
        ),
    )
    monkeypatch.setattr(
        tunnel_doctor,
        "check_tunnel",
        lambda *a, **k: calls.append(("tunnel", a, k)) or [doctor.ok("tunnel", "cfg")],
    )
    monkeypatch.setattr(
        tunnel_doctor,
        "check_tunnel_poller",
        lambda log: calls.append(("poller", log)) or [doctor.ok("poller", "ok")],
    )

    checks = tunnel_doctor.run_all()

    assert [c.group for c in checks] == ["tunnel", "tunnel", "tunnel", "poller"]
    assert calls[0] == ("drift", "binnacle-tunnel.service", "binnacle-tunnel")
    assert calls[1] == ("process", "binnacle-tunnel.service")
    assert calls[2][1] == (
        "binnacle-tunnel.service",
        pdir / "binnacle.yaml",
        tmp_path / "token",
        "http://127.0.0.1:8123/mcp",
    )
    assert calls[2][2] == {"server_unit": "binnacle-mcp.service"}
    assert calls[3] == ("poller", tmp_path / "t.log")

    (pdir / "binnacle.yaml").write_text("{}")
    calls.clear()
    assert [c.group for c in tunnel_doctor.run_all()] == ["tunnel", "tunnel", "tunnel"]
