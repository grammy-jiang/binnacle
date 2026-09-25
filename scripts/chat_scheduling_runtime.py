from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastmcp import Client

from scripts.chat_scheduling_manifest import Scenario

FIXTURE_BASE = Path("/tmp/binnacle-chat-scheduling-v2")
STATE_BASE = Path.home() / ".local" / "state" / "binnacle" / "chat-scheduling-v2"
PRODUCTION_REPO = Path.home() / "Projects" / "binnacle"
CONFIG_PATH = Path.home() / ".config" / "binnacle" / "config.toml"
UNIT_PATH = Path.home() / ".config" / "systemd" / "user" / "binnacle-mcp.service"
TOKEN_PATH = Path.home() / ".config" / "binnacle" / "token"
LOCAL_MCP_URL = "http://127.0.0.1:8000/mcp"
ROOT = Path(__file__).resolve().parents[1]
PHASE4 = Path.home() / ".local" / "state" / "binnacle" / "chat-scheduling-v2" / "phase4"
PHASE4_BENCH = ROOT / "benchmarks" / "chat-mode-scheduling-v2"
PHASE4_BASELINE = PHASE4_BENCH / "phase4-baseline.json"
PHASE4_TOPOLOGY = PHASE4_BENCH / "phase4-endpoint-topology-base.json"
PHASE4_LANES = PHASE4_BENCH / "phase4-lanes"
PHASE4_REGISTRY = PHASE4 / "endpoints.json"
SEND_GATE_SH = r"""set -euo pipefail; M=/home/grammy-jiang/.local/state/binnacle/p36-manager; Q=$M/sendq; mkdir -p "$Q"; T=$Q/$(date +%s%N)-$$; echo $$ > "$T"; trap 'rm -f "$T"' EXIT; while true; do O=$(ls "$Q" 2>/dev/null | sort | head -1); [ "$Q/$O" = "$T" ] && break; P=$(printf %s "$O" | sed "s/.*-//"); kill -0 "$P" 2>/dev/null || { rm -f "$Q/$O"; continue; }; sleep 5; done; exec 9>"$M/send.lock"; flock 9; G=$(cat "$M/$1" 2>/dev/null || echo 120); [ "$1" != trialgap ] || [ "$G" -ge 60 ] || G=60; L=$(cat "$M/last-send" 2>/dev/null || echo 0); N=$(date +%s); W=$((L+G-N)); [ "$W" -le 0 ] || sleep "$W"; printf "READY\n"; read -r S; [ "$S" != sent ] || date +%s > "$M/last-send" """


@contextmanager
def shared_send_gate(
    *, trial: bool, url_file: Path, timing_file: Path | None
) -> Generator[None, None, None]:
    gate = subprocess.Popen(
        ["bash", "-c", SEND_GATE_SH, "send-gate", "trialgap" if trial else "sendgap"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    if not gate.stdout or not gate.stdin or gate.stdout.readline().strip() != "READY":
        raise HarnessError("shared ChatGPT send gate failed")
    status = ""
    try:
        yield
    except BaseException:
        if url_file.exists() or (timing_file is not None and timing_file.exists()):
            status = "sent"
        raise
    else:
        status = "sent"
    finally:
        gate.stdin.write(status + "\n")
        gate.stdin.close()
        gate.wait(timeout=5)


class HarnessError(RuntimeError): ...


class RestoreError(HarnessError):
    def __init__(self, original: BaseException | None, restore: BaseException):
        self.original = original
        self.restore = restore
        detail = f"project-instruction restore failed: {restore}"
        if original is not None:
            detail += f"; original trial error was: {original}"
        super().__init__(detail)


@dataclass(frozen=True)
class TrialIdentity:
    scenario_id: str
    run_id: str
    nonce: str

    @classmethod
    def create(cls, scenario_id: str) -> TrialIdentity:
        stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S")
        run_id = f"{scenario_id.lower()}-{stamp}-{uuid.uuid4().hex[:10]}"
        return cls(scenario_id=scenario_id, run_id=run_id, nonce=secrets.token_hex(16))


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout: float | None = None,
    input_text: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        input=input_text,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=check,
    )


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def render_text(
    text: str,
    identity: TrialIdentity,
    root: Path,
    jobs: dict[str, str] | None = None,
    *,
    budget_s: int | None = None,
    margin_s: int | None = 0,
) -> str:
    replacements = {
        "id": identity.scenario_id,
        "run_id": identity.run_id,
        "nonce": identity.nonce,
        "root": str(root),
    }
    if budget_s is not None:
        replacements["budget_plus_margin_s"] = str(budget_s + (margin_s or 0))
    out = text
    for key, value in replacements.items():
        out = out.replace("{" + key + "}", value)
    for name, job_id in (jobs or {}).items():
        out = out.replace("{job:" + name + "}", job_id)
    if "{budget_plus_margin_s}" in out:
        raise HarnessError("runtime budget is required for this scenario")
    return out


@dataclass
class ProductionSnapshot:
    head: str
    status: str
    config_sha256: str | None
    unit_sha256: str | None
    active_state: str
    sub_state: str

    @classmethod
    def capture(cls) -> ProductionSnapshot:
        def unit_state(prop: str) -> str:
            args = [
                "systemctl",
                "--user",
                "show",
                "binnacle-mcp.service",
                "-p",
                prop,
                "--value",
            ]
            return _run(args).stdout.strip()

        return cls(
            head=_run(["git", "rev-parse", "HEAD"], cwd=PRODUCTION_REPO).stdout.strip(),
            status=_run(
                ["git", "status", "--porcelain=v1", "--untracked-files=normal"],
                cwd=PRODUCTION_REPO,
            ).stdout,
            config_sha256=_sha256(CONFIG_PATH),
            unit_sha256=_sha256(UNIT_PATH),
            active_state=unit_state("ActiveState"),
            sub_state=unit_state("SubState"),
        )

    def assert_unchanged(self, after: ProductionSnapshot) -> None:
        changed = []
        for name in (
            "head",
            "status",
            "config_sha256",
            "unit_sha256",
            "active_state",
            "sub_state",
        ):
            if getattr(self, name) != getattr(after, name):
                changed.append(name)
        if changed:
            raise HarnessError(
                "production invariant changed during benchmark: " + ", ".join(changed)
            )


class LocalMCP:
    def __init__(self, url: str = LOCAL_MCP_URL, token_path: Path = TOKEN_PATH) -> None:
        self.url = url
        self.token_path = token_path

    def _token(self) -> str:
        return (
            self.token_path.read_text(encoding="utf-8")
            .strip()
            .removeprefix("Bearer ")
            .strip()
        )

    async def _call_async(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        async with Client(self.url, auth=self._token()) as client:
            result = await client.call_tool(name, arguments)
            if result.structured_content is None:
                raise HarnessError(f"local MCP {name} returned no structured content")
            return result.structured_content

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return asyncio.run(self._call_async(name, arguments))

    def start_job(self, command: str, workdir: Path) -> str:
        out = self.call(
            "run_command",
            {
                "command": command,
                "workdir": str(workdir),
                "wait_seconds": 1,
                "background": True,
                "tail_lines": 20,
            },
        )
        job_id = out.get("job_id")
        if not job_id:
            raise HarnessError("fixture job did not return a job_id")
        return str(job_id)

    def stop_root_jobs(self, root: Path) -> list[str]:
        stopped: list[str] = []
        listing = self.call("job_status", {})
        for item in listing.get("jobs", []):
            if item.get("state") != "running":
                continue
            workdir = Path(item.get("workdir") or "/")
            if not _is_under(workdir, root):
                continue
            job_id = str(item["job_id"])
            self.call("stop_job", {"job_id": job_id})
            stopped.append(job_id)
        return stopped


@dataclass
class FixtureLease:
    scenario: Scenario
    identity: TrialIdentity
    mcp: LocalMCP
    budget_s: int | None = None
    root: Path = field(init=False)
    jobs: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        template = self.scenario.fixture.root_template
        if template is None:
            self.root = FIXTURE_BASE / self.identity.run_id
        else:
            self.root = Path(
                render_text(
                    template, self.identity, FIXTURE_BASE / self.identity.run_id
                )
            )
        if not _is_under(self.root, FIXTURE_BASE):
            raise HarnessError(f"unsafe fixture root: {self.root}")

    def __enter__(self) -> FixtureLease:  # noqa: PYI034 - Python 3.10-compatible forward reference
        if self.root.exists():
            raise HarnessError(f"fixture root already exists: {self.root}")
        self.root.mkdir(parents=True)
        for item in self.scenario.fixture.files:
            target = self.root / item.path
            if not _is_under(target, self.root):
                raise HarnessError(f"unsafe fixture file: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                render_text(item.content, self.identity, self.root),
                encoding="utf-8",
            )
        if self.scenario.fixture.kind == "ephemeral_git_repo":
            self._init_git()
        for job in self.scenario.fixture.jobs:
            if not job.prelaunch:
                continue
            command = render_text(
                job.command,
                self.identity,
                self.root,
                self.jobs,
                budget_s=self.budget_s,
                margin_s=self.scenario.runtime_budget_margin_s,
            )
            self.jobs[job.name] = self.mcp.start_job(command, self.root)
        return self

    def _init_git(self) -> None:
        _run(["git", "init", "-q"], cwd=self.root)
        _run(["git", "add", "-A"], cwd=self.root)
        _run(
            [
                "git",
                "-c",
                "user.name=Binnacle Benchmark",
                "-c",
                "user.email=benchmark.invalid@example.invalid",
                "commit",
                "-qm",
                "fixture baseline",
            ],
            cwd=self.root,
        )

    def rendered_prompt(self) -> str:
        return render_text(
            self.scenario.prompt_template,
            self.identity,
            self.root,
            self.jobs,
            budget_s=self.budget_s,
            margin_s=self.scenario.runtime_budget_margin_s,
        )

    def snapshot(self, target: Path) -> dict[str, Any]:
        final_files: dict[str, str] = {}
        file_hashes: dict[str, str] = {}
        for item in self.scenario.fixture.files:
            path = self.root / item.path
            if not path.exists() or not path.is_file():
                continue
            data = path.read_bytes()
            file_hashes[item.path] = hashlib.sha256(data).hexdigest()
            try:
                final_files[item.path] = data.decode("utf-8")
            except UnicodeDecodeError:
                pass
        payload: dict[str, Any] = {
            "root": str(self.root),
            "final_files": final_files,
            "file_sha256": file_hashes,
        }
        if (self.root / ".git").is_dir():
            payload["git_status_porcelain"] = _run(
                ["git", "status", "--porcelain=v1", "--untracked-files=all"],
                cwd=self.root,
            ).stdout
            payload["git_diff"] = _run(
                ["git", "diff", "--no-ext-diff", "--binary"],
                cwd=self.root,
            ).stdout
        write_json(target, payload)
        return payload

    def cleanup(self) -> dict[str, Any]:
        stopped: list[str] = []
        errors: list[str] = []
        try:
            stopped = self.mcp.stop_root_jobs(self.root)
        except Exception as exc:  # noqa: BLE001 - cleanup must continue to fixture removal
            errors.append(f"job cleanup: {exc}")
        try:
            if self.root.exists():
                shutil.rmtree(self.root)
        except Exception as exc:  # noqa: BLE001 - report cleanup failure in trial state
            errors.append(f"fixture cleanup: {exc}")
        return {
            "stopped_jobs": stopped,
            "errors": errors,
            "root_removed": not self.root.exists(),
        }

    def __exit__(self, exc_type, exc, tb) -> Literal[False]:
        cleanup = self.cleanup()
        if cleanup["errors"] and exc is None:
            raise HarnessError("; ".join(cleanup["errors"]))
        return False


def _file_sha(path: Path) -> str:
    if not path.is_file():
        raise HarnessError(f"required file is missing: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_arm_endpoint(arm: str, budget_s: int | None, endpoint: str) -> int | None:
    if arm in {"A", "B"} and budget_s is None and endpoint == arm:
        return None
    if arm == "H" and endpoint == "H" and budget_s in {None, 10}:
        return 10
    elif arm == "C" and budget_s is not None and endpoint == f"C{budget_s}":
        return budget_s
    raise HarnessError("arm/budget/endpoint combination is invalid")


def resolve_phase4_endpoint(
    arm: str,
    budget_s: int | None,
    endpoint_id: str,
    *,
    sources: dict[str, Any] | None = None,
) -> dict[str, Any]:
    def load(path: Path) -> dict[str, Any]:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise HarnessError(f"JSON object required: {path}")
        return value

    def endpoint(data: dict[str, Any]) -> dict[str, Any]:
        raw = data.get("endpoints", {})
        if isinstance(raw, dict) and isinstance(raw.get(endpoint_id), dict):
            return dict(raw[endpoint_id])
        if isinstance(raw, list):
            found = [
                x
                for x in raw
                if isinstance(x, dict) and x.get("endpoint_id") == endpoint_id
            ]
            if len(found) == 1:
                return dict(found[0])
        raise HarnessError(f"endpoint {endpoint_id} is absent")

    budget_s = validate_arm_endpoint(arm, budget_s, endpoint_id)
    src = sources or {}
    baseline_path = Path(src.get("baseline", PHASE4_BASELINE))
    topology_path = Path(src.get("topology", PHASE4_TOPOLOGY))
    lanes = Path(src.get("lanes", PHASE4_LANES))
    registry_path = Path(src.get("registry", PHASE4_REGISTRY))
    baseline, topology, registry = (
        load(x) for x in (baseline_path, topology_path, registry_path)
    )
    source_head = baseline.get("phase4_source_head")
    base, live = endpoint(topology), endpoint(registry)
    manifest_path = lanes / f"{endpoint_id}.json"
    manifest, topology_sha = load(manifest_path), _file_sha(topology_path)
    rows = ((endpoint_id, *(x.get("endpoint_id") for x in (base, manifest, live))), (arm, *(x.get("logical_arm") for x in (base, manifest, live))), (budget_s, *(x.get("budget_s") for x in (base, manifest, live))), (base.get("port"), manifest.get("port"), live.get("port")), (base.get("tunnel_profile"), manifest.get("tunnel_profile"), live.get("tunnel_profile")))  # fmt: skip
    if any(any(value != row[0] for value in row[1:]) for row in rows):
        raise HarnessError("endpoint topology/runtime identity mismatch")
    if manifest.get("attachment_status") != "verified":
        raise HarnessError("lane manifest is not attachment-verified")
    if any(
        x.get("phase4_source_head") != source_head
        for x in (topology, manifest, registry, live)
    ):
        raise HarnessError("phase4_source_head mismatch")
    if manifest.get("base_topology_sha256") != topology_sha:
        raise HarnessError("base topology hash mismatch")
    inst = baseline[
        "benchmark_source_project" if arm == "A" else "canonical_v2_instruction"
    ]
    inst_path = Path(
        inst.get("instructions_snapshot_path", inst.get("path", ""))
    ).expanduser()
    if not inst_path.is_absolute():
        inst_path = ROOT / inst_path
    inst_sha = inst.get("instructions_sha256", inst.get("sha256"))
    if _file_sha(inst_path) != inst_sha or manifest.get("instruction_sha256") != inst_sha:  # fmt: skip
        raise HarnessError("instruction hash mismatch")
    process_ids = live.get("process_start_identity", {})
    for role in ("server", "manager", "tunnel"):
        pid = int(live[f"{role}_pid"])
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        ticks = raw[raw.rfind(") ") + 2 :].split()[19]
        expected = process_ids.get(role)
        matches = (
            expected.get("pid") == pid and expected.get("start_time_ticks") == ticks
            if isinstance(expected, dict)
            else expected == f"{pid}:{ticks}"
        )
        if not matches:
            raise HarnessError(f"stale {role} process identity")
    for key in ("token_path", "server_log_path", "manager_log_path", "tunnel_log_path"):
        if not Path(live[key]).expanduser().is_file():
            raise HarnessError(f"runtime endpoint lacks {key}")
    return {**live, "project_name": manifest["project_name"], "project_id": manifest["project_id"], "connector_logical_name": manifest["connector_logical_name"], "logical_arm": arm, "budget_s": budget_s, "instruction_sha256": inst_sha, "model_thinking": baseline["model_thinking"], "phase4_source_head": source_head, "base_topology_sha256": topology_sha, "lane_manifest_path": str(manifest_path), "lane_manifest_sha256": _file_sha(manifest_path), "runtime_registry_sha256": _file_sha(registry_path), "admission_envelope_revision": src.get("admission_revision")}  # fmt: skip


def new_state_dir(identity: TrialIdentity, base: Path = STATE_BASE) -> Path:
    path = base / "runs" / identity.run_id
    path.mkdir(parents=True, exist_ok=False)
    return path


def write_json(path: Path, value: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
