"""Launch and supervise isolated Phase-4 benchmark endpoints."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.chat_scheduling_historical_guard import (
    atomic_json,
    identity,
    load_env,
    manager_healthy,
    mcp_healthy,
    port_in_use,
    process_matches,
    spawn,
    terminate,
    tunnel_healthy,
    wait_ready,
)

PHASE4_SOURCE_HEAD = "06bc1649c4bad9449470366da971649bb7620020"
REPO_ROOT = Path(__file__).resolve().parents[1]
INPUT_CONTRACT = (
    REPO_ROOT / "benchmarks/chat-mode-scheduling-v2/phase4-input-contract.json"
)
TUNNEL_CLIENT = Path.home() / ".local/bin/tunnel-client"
TUNNEL_PROFILE_DIR = Path.home() / ".config/tunnel-client"
TUNNEL_HEALTH_DIR = Path.home() / ".local/state/tunnel-client/health"


@dataclass(frozen=True, slots=True)
class Endpoint:
    endpoint_id: str
    logical_arm: str
    budget_s: int | None
    host: str
    port: int
    server_process_identity: str
    tunnel_profile: str
    connector_logical_name: str
    project_name: str


def _endpoint(endpoint_id: str, arm: str, budget: int | None, port: int) -> Endpoint:
    profile = f"binnacle-sched-{endpoint_id.lower()}"
    return Endpoint(
        endpoint_id,
        arm,
        budget,
        "127.0.0.1",
        port,
        profile,
        profile,
        f"Raspberry Pi MCP Scheduling {endpoint_id}",
        f"rp-sched-{endpoint_id}",
    )


ENDPOINTS = {
    item.endpoint_id: item
    for item in (
        _endpoint("A", "A", None, 8110),
        _endpoint("B", "B", None, 8111),
        _endpoint("C120", "C", 120, 8112),
        _endpoint("C300", "C", 300, 8113),
        _endpoint("C600", "C", 600, 8114),
        _endpoint("H", "H", 10, 8115),
    )
}


def static_topology() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "phase": 4,
        "phase4_source_head": PHASE4_SOURCE_HEAD,
        "endpoints": [asdict(item) for item in ENDPOINTS.values()],
    }


def live_endpoint_ids() -> tuple[str, ...]:
    data = json.loads(INPUT_CONTRACT.read_text(encoding="utf-8"))
    candidates = tuple(map(str, data["live_candidates"]))
    invalid = set(candidates) - {"C120", "C300", "C600"}
    if invalid:
        raise RuntimeError(f"invalid Phase-3 live candidate ids: {sorted(invalid)}")
    return ("A", "B", *candidates, "H")


def _selected(raw_ids: list[str]) -> list[str]:
    allowed = set(live_endpoint_ids())
    selected: list[str] = []
    for endpoint_id in raw_ids:
        if endpoint_id not in ENDPOINTS:
            raise ValueError(
                f"unknown endpoint {endpoint_id!r}; reserved ids are A/B/C120/C300/C600/H"
            )
        if endpoint_id not in allowed:
            raise ValueError(
                f"endpoint {endpoint_id} is reserved but is not a Phase-3 live candidate"
            )
        if endpoint_id not in selected:
            selected.append(endpoint_id)
    return selected


def _paths(root: Path, endpoint_id: str) -> dict[str, Path]:
    lane = root / endpoint_id
    return {
        "root": lane,
        "config": lane / "config.toml",
        "token": lane / "token",
        "jobs_dir": lane / "jobs",
        "socket": lane / "jobs.sock",
        "server_log": lane / "server.log",
        "manager_log": lane / "manager.log",
        "tunnel_log": lane / "tunnel.log",
        "pids": lane / "pids.json",
    }


def runtime_registry_path(root: Path) -> Path:
    return root.parent / "endpoints.json"


def _registry(root: Path) -> dict[str, Any]:
    path = runtime_registry_path(root)
    if not path.exists():
        return {
            "schema_version": 1,
            "phase4_source_head": PHASE4_SOURCE_HEAD,
            "endpoints": {},
        }
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("phase4_source_head") != PHASE4_SOURCE_HEAD:
        raise RuntimeError(
            "runtime registry phase4_source_head does not match frozen source"
        )
    if not isinstance(data.get("endpoints"), dict):
        raise TypeError("runtime registry endpoints must be an object")
    return data


def _config_text(spec: Endpoint, paths: dict[str, Path]) -> str:
    budget = (
        "{}" if spec.logical_arm != "C" else f'{{ "openai-mcp" = {spec.budget_s} }}'
    )
    quote = json.dumps
    return (
        "[auth]\n"
        f"token_file = {quote(str(paths['token']))}\n\n"
        "[serve]\n"
        f"host = {quote(spec.host)}\n"
        f"port = {spec.port}\n\n"
        "[jobs]\n"
        'owner = "manager"\n'
        f"socket_path = {quote(str(paths['socket']))}\n"
        f"dir = {quote(str(paths['jobs_dir']))}\n"
        f"blocking_wall_budget_s_by_client = {budget}\n"
    )


def _prepare(spec: Endpoint, root: Path) -> dict[str, Path]:
    paths = _paths(root, spec.endpoint_id)
    for directory in (paths["root"], paths["jobs_dir"]):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
    if not paths["token"].exists():
        paths["token"].write_text(
            f"Bearer {secrets.token_urlsafe(32)}\n", encoding="utf-8"
        )
    paths["token"].chmod(0o600)
    paths["config"].write_text(_config_text(spec, paths), encoding="utf-8")
    paths["config"].chmod(0o600)
    for name in ("server_log", "manager_log", "tunnel_log"):
        fd = os.open(paths[name], os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        os.close(fd)
        paths[name].chmod(0o600)
    return paths


def _base_entry(spec: Endpoint, root: Path) -> dict[str, Any]:
    paths = _paths(root, spec.endpoint_id)
    return {
        **asdict(spec),
        "phase4_source_head": PHASE4_SOURCE_HEAD,
        "config_path": str(paths["config"]),
        "token_path": str(paths["token"]),
        "jobs_dir": str(paths["jobs_dir"]),
        "socket_path": str(paths["socket"]),
        "server_log_path": str(paths["server_log"]),
        "manager_log_path": str(paths["manager_log"]),
        "tunnel_log_path": str(paths["tunnel_log"]),
        "tunnel_health_url_path": str(TUNNEL_HEALTH_DIR / f"{spec.tunnel_profile}.url"),
    }


def _matches(role: str, entry: dict[str, Any]) -> bool:
    return process_matches(role, entry, REPO_ROOT)


def _static_ok(entry: dict[str, Any], spec: Endpoint, root: Path) -> bool:
    return all(
        entry.get(key) == value for key, value in _base_entry(spec, root).items()
    )


def _local_healthy(entry: dict[str, Any], spec: Endpoint, root: Path) -> bool:
    paths = _paths(root, spec.endpoint_id)
    if not _static_ok(entry, spec, root):
        return False
    try:
        config_ok = paths["config"].read_text(encoding="utf-8") == _config_text(
            spec, paths
        )
    except OSError:
        return False
    return (
        config_ok
        and _matches("manager", entry)
        and _matches("server", entry)
        and manager_healthy(paths["socket"])
        and mcp_healthy(spec.host, spec.port, paths["token"])
    )


def _server_command(spec: Endpoint) -> list[str]:
    if spec.endpoint_id == "H":
        return [
            "uv",
            "run",
            "python",
            "scripts/chat_scheduling_historical_guard.py",
            "serve",
            "--host",
            spec.host,
            "--port",
            str(spec.port),
        ]
    return [
        "uv",
        "run",
        "binnacle",
        "serve",
        "--host",
        spec.host,
        "--port",
        str(spec.port),
    ]


def _write_pids(root: Path, entry: dict[str, Any]) -> None:
    atomic_json(
        _paths(root, entry["endpoint_id"])["pids"],
        {
            "endpoint_id": entry["endpoint_id"],
            "server_pid": entry["server_pid"],
            "manager_pid": entry["manager_pid"],
            "tunnel_pid": entry["tunnel_pid"],
            "process_start_identity": entry["process_start_identity"],
        },
    )


def _start_one(root: Path, spec: Endpoint) -> dict[str, Any]:
    paths = _prepare(spec, root)
    env = os.environ.copy()
    env["BINNACLE_CONFIG_FILE"] = str(paths["config"])
    manager = spawn(
        ["uv", "run", "binnacle-jobs"], paths["manager_log"], env, REPO_ROOT
    )
    server = None
    try:
        wait_ready(
            manager_healthy, manager, f"{spec.endpoint_id} manager", paths["socket"]
        )
        server = spawn(_server_command(spec), paths["server_log"], env, REPO_ROOT)
        wait_ready(
            mcp_healthy,
            server,
            f"{spec.endpoint_id} server",
            spec.host,
            spec.port,
            paths["token"],
        )
        entry = {
            **_base_entry(spec, root),
            "server_pid": server.pid,
            "manager_pid": manager.pid,
            "tunnel_pid": None,
            "process_start_identity": {
                "manager": identity(manager.pid),
                "server": identity(server.pid),
                "tunnel": None,
            },
        }
        _write_pids(root, entry)
        return entry
    except BaseException:
        if server is not None:
            terminate(server.pid)
        terminate(manager.pid)
        raise


def _check_reserved_ports(registry: dict[str, Any], root: Path) -> None:
    for spec in ENDPOINTS.values():
        if not port_in_use(spec.host, spec.port):
            continue
        entry = registry["endpoints"].get(spec.endpoint_id)
        if not isinstance(entry, dict) or not _local_healthy(entry, spec, root):
            raise RuntimeError(
                f"reserved port {spec.port} for {spec.endpoint_id} is already in use"
            )


def start_local(root: Path, raw_ids: list[str]) -> None:
    selected = _selected(raw_ids)
    registry = _registry(root)
    _check_reserved_ports(registry, root)
    started: list[tuple[str, int, int]] = []
    try:
        for endpoint_id in selected:
            spec = ENDPOINTS[endpoint_id]
            existing = registry["endpoints"].get(endpoint_id)
            if isinstance(existing, dict):
                if _local_healthy(existing, spec, root):
                    continue
                raise RuntimeError(
                    f"endpoint {endpoint_id} has stale/mismatched runtime identity"
                )
            entry = _start_one(root, spec)
            registry["endpoints"][endpoint_id] = entry
            started.append((endpoint_id, entry["server_pid"], entry["manager_pid"]))
        atomic_json(runtime_registry_path(root), registry)
    except BaseException:
        for endpoint_id, server_pid, manager_pid in reversed(started):
            terminate(server_pid)
            terminate(manager_pid)
            registry["endpoints"].pop(endpoint_id, None)
        atomic_json(runtime_registry_path(root), registry)
        raise


def _start_tunnel(root: Path, spec: Endpoint, entry: dict[str, Any]) -> None:
    profile = TUNNEL_PROFILE_DIR / f"{spec.tunnel_profile}.yaml"
    env_file = TUNNEL_PROFILE_DIR / f"{spec.tunnel_profile}-tunnel.env"
    if not profile.is_file() or not env_file.is_file():
        raise RuntimeError(
            f"endpoint {spec.endpoint_id} tunnel profile/env file is absent"
        )
    url_path = TUNNEL_HEALTH_DIR / f"{spec.tunnel_profile}.url"
    old_mtime = url_path.stat().st_mtime_ns if url_path.exists() else None
    env = os.environ.copy()
    env.update(load_env(env_file))
    command = [
        str(TUNNEL_CLIENT),
        "run",
        "--profile-dir",
        str(TUNNEL_PROFILE_DIR),
        "--profile",
        spec.tunnel_profile,
    ]
    proc = spawn(command, Path(entry["tunnel_log_path"]), env, REPO_ROOT)
    try:
        wait_ready(
            tunnel_healthy, proc, f"{spec.endpoint_id} tunnel", url_path, old_mtime
        )
        entry["tunnel_pid"] = proc.pid
        entry["process_start_identity"]["tunnel"] = identity(proc.pid)
        _write_pids(root, entry)
    except BaseException:
        entry["tunnel_pid"] = None
        entry["process_start_identity"]["tunnel"] = None
        terminate(proc.pid)
        raise


def start_tunnels(root: Path, raw_ids: list[str]) -> None:
    registry = _registry(root)
    for endpoint_id in _selected(raw_ids):
        spec = ENDPOINTS[endpoint_id]
        entry = registry["endpoints"].get(endpoint_id)
        if not isinstance(entry, dict) or not _local_healthy(entry, spec, root):
            raise RuntimeError(f"endpoint {endpoint_id} is not locally healthy")
        if entry.get("tunnel_pid") is not None:
            if _matches("tunnel", entry):
                continue
            raise RuntimeError(
                f"endpoint {endpoint_id} has stale/mismatched tunnel identity"
            )
        _start_tunnel(root, spec, entry)
        atomic_json(runtime_registry_path(root), registry)


def status(root: Path) -> int:
    registry = _registry(root)
    result: dict[str, Any] = {}
    failed = False
    for endpoint_id, entry in registry["endpoints"].items():
        spec = ENDPOINTS.get(endpoint_id)
        local = bool(
            spec and isinstance(entry, dict) and _local_healthy(entry, spec, root)
        )
        tunnel = "not_started"
        if isinstance(entry, dict) and entry.get("tunnel_pid") is not None:
            tunnel = "healthy" if _matches("tunnel", entry) else "stale"
        failed |= not local or tunnel == "stale"
        result[endpoint_id] = {
            "local": "healthy" if local else "stale",
            "tunnel": tunnel,
        }
    print(
        json.dumps(
            {"phase4_source_head": PHASE4_SOURCE_HEAD, "endpoints": result},
            sort_keys=True,
        )
    )
    return int(failed)


def stop(root: Path) -> int:
    registry = _registry(root)
    report: dict[str, Any] = {}
    failed = False
    for endpoint_id, entry in list(registry["endpoints"].items()):
        spec = ENDPOINTS.get(endpoint_id)
        lane_identity_ok = bool(spec and _static_ok(entry, spec, root))
        lane_ok = True
        actions: list[str] = []
        for role in ("tunnel", "server", "manager"):
            pid = entry.get(f"{role}_pid")
            if pid is None:
                continue
            if not lane_identity_ok or not _matches(role, entry):
                actions.append(f"{role}:stale-not-signalled")
                lane_ok = False
            else:
                terminate(pid)
                actions.append(f"{role}:stopped")
        if lane_ok:
            registry["endpoints"].pop(endpoint_id, None)
        else:
            failed = True
        report[endpoint_id] = actions
    atomic_json(runtime_registry_path(root), registry)
    print(json.dumps(report, sort_keys=True))
    return int(failed)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("start-local", "start-tunnels"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--root", type=Path, required=True)
        sub.add_argument("--endpoint", action="append", required=True)
    for command in ("status", "stop"):
        subparsers.add_parser(command).add_argument("--root", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "start-local":
            start_local(args.root, args.endpoint)
        elif args.command == "start-tunnels":
            start_tunnels(args.root, args.endpoint)
        elif args.command == "status":
            return status(args.root)
        elif args.command == "stop":
            return stop(args.root)
    except (OSError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
