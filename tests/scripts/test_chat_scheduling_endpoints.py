from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from scripts import chat_scheduling_endpoints as endpoints


class FakeProc:
    def __init__(self, pid: int):
        self.pid = pid

    def poll(self):
        return None


def _runtime_entry(root: Path, endpoint_id: str) -> dict:
    spec = endpoints.ENDPOINTS[endpoint_id]
    entry = {
        **endpoints._base_entry(spec, root),
        "server_pid": 102,
        "manager_pid": 101,
        "tunnel_pid": None,
        "process_start_identity": {
            "manager": {"pid": 101, "start_time_ticks": "m"},
            "server": {"pid": 102, "start_time_ticks": "s"},
            "tunnel": None,
        },
    }
    return entry


def _write_registry(root: Path, entries: dict[str, dict]) -> None:
    endpoints.atomic_json(
        endpoints.runtime_registry_path(root),
        {
            "schema_version": 1,
            "phase4_source_head": endpoints.PHASE4_SOURCE_HEAD,
            "endpoints": entries,
        },
    )


def test_static_topology_file_matches_frozen_reserved_lanes():
    path = (
        endpoints.REPO_ROOT
        / "benchmarks/chat-mode-scheduling-v2/phase4-endpoint-topology-base.json"
    )
    assert json.loads(path.read_text(encoding="utf-8")) == endpoints.static_topology()

    rows = endpoints.static_topology()["endpoints"]
    assert [(row["endpoint_id"], row["port"]) for row in rows] == [
        ("A", 8110),
        ("B", 8111),
        ("C120", 8112),
        ("C300", 8113),
        ("C600", 8114),
        ("H", 8115),
    ]
    assert [row["tunnel_profile"] for row in rows] == [
        "binnacle-sched-a",
        "binnacle-sched-b",
        "binnacle-sched-c120",
        "binnacle-sched-c300",
        "binnacle-sched-c600",
        "binnacle-sched-h",
    ]
    assert rows[0]["connector_logical_name"] == "Raspberry Pi MCP Scheduling A"
    assert rows[-1]["project_name"] == "rp-sched-H"


def test_live_endpoint_list_comes_from_phase3_shortlist():
    assert endpoints.live_endpoint_ids() == ("A", "B", "C300", "H")
    assert endpoints._selected(["A", "C300", "H"]) == ["A", "C300", "H"]
    with pytest.raises(ValueError, match="not a Phase-3 live candidate"):
        endpoints._selected(["C120"])
    with pytest.raises(ValueError, match="unknown endpoint"):
        endpoints._selected(["C999"])


def test_generated_configs_are_isolated_and_only_c_has_cumulative_budget(tmp_path):
    root = tmp_path / "endpoints"
    a_paths = endpoints._paths(root, "A")
    c_paths = endpoints._paths(root, "C300")
    h_paths = endpoints._paths(root, "H")
    a = endpoints._config_text(endpoints.ENDPOINTS["A"], a_paths)
    c = endpoints._config_text(endpoints.ENDPOINTS["C300"], c_paths)
    h = endpoints._config_text(endpoints.ENDPOINTS["H"], h_paths)

    assert (
        'owner = "manager"' in a
        and 'owner = "manager"' in c
        and 'owner = "manager"' in h
    )
    assert "blocking_wall_budget_s_by_client = {}" in a
    assert "blocking_wall_budget_s_by_client = {}" in h
    assert 'blocking_wall_budget_s_by_client = { "openai-mcp" = 300 }' in c
    assert f'dir = "{root / "C300" / "jobs"}"' in c
    assert f'socket_path = "{root / "C300" / "jobs.sock"}"' in c
    assert f'token_file = "{root / "C300" / "token"}"' in c


def test_h_server_command_requires_benchmark_adapter():
    assert endpoints._server_command(endpoints.ENDPOINTS["H"]) == [
        "uv",
        "run",
        "python",
        "scripts/chat_scheduling_historical_guard.py",
        "serve",
        "--host",
        "127.0.0.1",
        "--port",
        "8115",
    ]
    assert endpoints._server_command(endpoints.ENDPOINTS["A"]) == [
        "uv",
        "run",
        "binnacle",
        "serve",
        "--host",
        "127.0.0.1",
        "--port",
        "8110",
    ]


def test_start_local_writes_private_registry_and_separate_manager_server(
    monkeypatch, tmp_path
):
    root = tmp_path / "endpoints"
    calls = []
    pids = iter((101, 102))

    def fake_spawn(command, log_path, env, repo_root):
        calls.append((command, log_path, env["BINNACLE_CONFIG_FILE"], repo_root))
        return FakeProc(next(pids))

    monkeypatch.setattr(endpoints, "port_in_use", lambda host, port: False)
    monkeypatch.setattr(endpoints, "spawn", fake_spawn)
    monkeypatch.setattr(endpoints, "wait_ready", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        endpoints,
        "identity",
        lambda pid: {"pid": pid, "start_time_ticks": f"ticks-{pid}"},
    )

    endpoints.start_local(root, ["A"])
    registry_path = endpoints.runtime_registry_path(root)
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    entry = registry["endpoints"]["A"]

    assert stat.S_IMODE(registry_path.stat().st_mode) == 0o600
    assert entry["phase4_source_head"] == endpoints.PHASE4_SOURCE_HEAD
    assert entry["config_path"] == str(root / "A" / "config.toml")
    assert entry["token_path"] == str(root / "A" / "token")
    assert entry["jobs_dir"] == str(root / "A" / "jobs")
    assert entry["socket_path"] == str(root / "A" / "jobs.sock")
    assert entry["server_pid"] == 102 and entry["manager_pid"] == 101
    assert entry["tunnel_pid"] is None
    assert calls[0][0] == ["uv", "run", "binnacle-jobs"]
    assert calls[1][0][-4:] == ["--host", "127.0.0.1", "--port", "8110"]
    assert calls[0][2] == calls[1][2] == str(root / "A" / "config.toml")
    assert calls[0][3] == calls[1][3] == endpoints.REPO_ROOT


def test_reserved_port_collision_fails_before_any_spawn(monkeypatch, tmp_path):
    root = tmp_path / "endpoints"
    monkeypatch.setattr(
        endpoints,
        "port_in_use",
        lambda host, port: port == endpoints.ENDPOINTS["C600"].port,
    )
    monkeypatch.setattr(
        endpoints,
        "spawn",
        lambda *args, **kwargs: pytest.fail(
            "must not spawn with reserved-port collision"
        ),
    )
    with pytest.raises(RuntimeError, match="reserved port 8114"):
        endpoints.start_local(root, ["A"])


def test_stale_existing_runtime_identity_refuses_restart(monkeypatch, tmp_path):
    root = tmp_path / "endpoints"
    entry = _runtime_entry(root, "A")
    _write_registry(root, {"A": entry})
    monkeypatch.setattr(endpoints, "port_in_use", lambda host, port: False)
    monkeypatch.setattr(
        endpoints,
        "spawn",
        lambda *args, **kwargs: pytest.fail("stale identity must not be replaced"),
    )

    with pytest.raises(RuntimeError, match="stale/mismatched runtime identity"):
        endpoints.start_local(root, ["A"])


def test_stop_never_signals_a_stale_or_reused_pid(monkeypatch, tmp_path, capsys):
    root = tmp_path / "endpoints"
    entry = _runtime_entry(root, "A")
    entry["config_path"] = "/tampered/config.toml"
    _write_registry(root, {"A": entry})
    monkeypatch.setattr(endpoints, "_matches", lambda role, entry: True)
    monkeypatch.setattr(
        endpoints,
        "terminate",
        lambda pid: pytest.fail("stale PID must never be signalled"),
    )

    assert endpoints.stop(root) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["A"] == [
        "server:stale-not-signalled",
        "manager:stale-not-signalled",
    ]
    registry = json.loads(
        endpoints.runtime_registry_path(root).read_text(encoding="utf-8")
    )
    assert "A" in registry["endpoints"]


def test_start_tunnels_requires_local_health_and_profile_files(monkeypatch, tmp_path):
    root = tmp_path / "endpoints"
    _write_registry(root, {"A": _runtime_entry(root, "A")})
    monkeypatch.setattr(endpoints, "_local_healthy", lambda entry, spec, root: True)
    monkeypatch.setattr(endpoints, "TUNNEL_PROFILE_DIR", tmp_path / "profiles")
    monkeypatch.setattr(
        endpoints,
        "spawn",
        lambda *args, **kwargs: pytest.fail("missing profile must not spawn"),
    )

    with pytest.raises(RuntimeError, match="profile/env file is absent"):
        endpoints.start_tunnels(root, ["A"])


def test_start_tunnels_uses_fixed_profile_and_records_identity(monkeypatch, tmp_path):
    root = tmp_path / "endpoints"
    entry = _runtime_entry(root, "A")
    _write_registry(root, {"A": entry})
    profiles = tmp_path / "profiles"
    health = tmp_path / "health"
    profiles.mkdir()
    health.mkdir()
    (profiles / "binnacle-sched-a.yaml").write_text("profile: test\n", encoding="utf-8")
    (profiles / "binnacle-sched-a-tunnel.env").write_text(
        "OPENAI_API_KEY='private-test-value'\n", encoding="utf-8"
    )
    calls = []

    def fake_spawn(command, log_path, env, repo_root):
        calls.append((command, log_path, env, repo_root))
        return FakeProc(303)

    monkeypatch.setattr(endpoints, "_local_healthy", lambda entry, spec, root: True)
    monkeypatch.setattr(endpoints, "TUNNEL_PROFILE_DIR", profiles)
    monkeypatch.setattr(endpoints, "TUNNEL_HEALTH_DIR", health)
    monkeypatch.setattr(endpoints, "TUNNEL_CLIENT", Path("/test/tunnel-client"))
    monkeypatch.setattr(endpoints, "spawn", fake_spawn)
    monkeypatch.setattr(endpoints, "wait_ready", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        endpoints,
        "identity",
        lambda pid: {"pid": pid, "start_time_ticks": "tunnel-ticks"},
    )

    endpoints.start_tunnels(root, ["A"])
    command, log_path, env, repo_root = calls[0]
    assert command == [
        "/test/tunnel-client",
        "run",
        "--profile-dir",
        str(profiles),
        "--profile",
        "binnacle-sched-a",
    ]
    assert log_path == Path(entry["tunnel_log_path"])
    assert env["OPENAI_API_KEY"] == "private-test-value"
    assert repo_root == endpoints.REPO_ROOT
    registry = json.loads(
        endpoints.runtime_registry_path(root).read_text(encoding="utf-8")
    )
    assert registry["endpoints"]["A"]["tunnel_pid"] == 303
    assert registry["endpoints"]["A"]["process_start_identity"]["tunnel"] == {
        "pid": 303,
        "start_time_ticks": "tunnel-ticks",
    }


def test_start_tunnels_rejects_locally_unhealthy_endpoint(monkeypatch, tmp_path):
    root = tmp_path / "endpoints"
    _write_registry(root, {"A": _runtime_entry(root, "A")})
    monkeypatch.setattr(endpoints, "_local_healthy", lambda entry, spec, root: False)
    with pytest.raises(RuntimeError, match="not locally healthy"):
        endpoints.start_tunnels(root, ["A"])
