"""OS6 exhaustive tracked and new Python ownership/reverse dependency inventory.

Run from the implementation worktree using:
    uv run python -m scripts.os_stage1_inventory

Immutable OS0 evidence is never overwritten. This report is an inventory
only; it cannot convert a failed independent review or Linux live gate to pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from scripts import check_architecture as architecture
from scripts.os_independence import inspect_source_tree

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "os-independent-stage1-evidence"
PREFIXES = ("src/binnacle/", "scripts/")
LINUX_PREFIXES = (
    "src/binnacle/platform/linux/",
    "src/binnacle/deployment/linux/",
    "src/binnacle/observability/linux/",
    "src/binnacle/companions/",
)
BOUNDARIES = frozenset(
    {
        "src/binnacle/application.py",
        "src/binnacle/server.py",
        "src/binnacle/config.py",
        "src/binnacle/cli.py",
        "src/binnacle/platform/composition.py",
        "src/binnacle/platform/job_platform.py",
        "src/binnacle/platform/deployment_platform.py",
        "src/binnacle/features/commands/jobs.py",
        "src/binnacle/features/commands/job_manager.py",
        "src/binnacle/features/commands/job_stop.py",
        "src/binnacle/features/commands/job_owner.py",
        "src/binnacle/features/files/paths.py",
        "src/binnacle/deployment/units.py",
        "src/binnacle/deployment/provisioning_contracts.py",
        "src/binnacle/diagnostics/doctor.py",
        "src/binnacle/diagnostics/doctor_jobs.py",
        "src/binnacle/observability/logstats.py",
        "src/binnacle/observability/logstats_io.py",
        "src/binnacle/observability/log_safety.py",
        "src/binnacle/observability/system_resource_history.py",
    }
)
LINUX_SCRIPTS = frozenset(
    {
        "resource_monitor.py",
        "chat_scheduling_runtime.py",
        "migrate_resource_history_v2.py",
        "weekly_bench.py",
        "weekly_host.py",
        "weekly_scope.py",
        "deploy_flow.py",
        "deploy_smoke.py",
        "smoke_checks.py",
    }
)
HOST_TOKENS = (
    "systemctl",
    "journalctl",
    "loginctl",
    "NOTIFY_SOCKET",
    "/proc/",
    "/sys/fs/cgroup",
)
STAGE_SEAMS = {
    "server.py": "OS2",
    "application.py": "OS2",
    "config.py": "OS2",
    "jobs.py": "OS3",
    "job_stop.py": "OS3",
    "job_owner.py": "OS3",
    "job_manager.py": "OS3",
    "job_process.py": "OS3",
    "job_identity.py": "OS3",
    "job_cgroup.py": "OS3",
    "notify_systemd.py": "OS3",
    "cli.py": "OS4",
    "units.py": "OS4",
    "provisioning_contracts.py": "OS4",
    "unit_inspection.py": "OS4",
    "service_systemd.py": "OS4",
    "service_provisioning_linux.py": "OS4",
    "doctor.py": "OS5",
    "linux_checks.py": "OS5",
    "logstats.py": "OS5",
    "logstats_io.py": "OS5",
    "paths.py": "OS5",
    "log_safety.py": "OS5",
    "os_independence.py": "OS6",
    "os_stage1_inventory.py": "OS6",
}


def code_paths(root: Path = ROOT) -> list[str]:
    """Account for tracked AND added/untracked Python modules before commit."""
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    names = (n.decode() for n in result.stdout.split(b"\0") if n)
    return sorted(
        name
        for name in names
        if name.endswith(".py")
        and name.startswith(PREFIXES)
        and (root / name).is_file()
    )


def classify(path: str, baseline: dict[str, Any]) -> tuple[str, str, str]:
    """KEEP decisions must have an explicit business-level justification."""
    short = Path(path).name
    stage = STAGE_SEAMS.get(short, "OS6")
    original = baseline.get(path)
    if (
        path.startswith(LINUX_PREFIXES)
        or path == "src/binnacle/diagnostics/linux_checks.py"
    ):
        return (
            "LINUX",
            stage,
            "Linux-specific host, service or companion implementation; core must never import it directly",
        )
    if path.startswith("scripts/") and short in LINUX_SCRIPTS:
        return (
            "LINUX",
            stage,
            "Linux production/development host utility, not a portable application dependency",
        )
    if path in BOUNDARIES or (original and original.get("owner") == "SPLIT"):
        return (
            "BOUNDARY",
            stage,
            "Explicit composition or compatibility seam; implementation-specific actions are delegated",
        )
    if path.startswith("scripts/"):
        return (
            "KEEP",
            stage,
            "External repository management/testing; subprocess for Git, uv or ripgrep is portable, not a host adapter",
        )
    if "/contracts/" in path or path.endswith("command_contracts.py"):
        return (
            "KEEP",
            stage,
            "Narrow value types and Protocol contracts contain no platform implementation",
        )
    if "/mcp/" in path or "/tools/" in path or path.endswith("_server.py"):
        return (
            "KEEP",
            stage,
            "FastMCP-native integration; MCP framework remains solely responsible for Providers and Middleware",
        )
    if "/search/" in path:
        return (
            "KEEP",
            stage,
            "Portable ripgrep and application search policy; external executable is not Linux-specific",
        )
    if "/features/files/" in path:
        return (
            "KEEP",
            stage,
            "Generic file/tool policy implemented through pathlib and existing root authorization checks",
        )
    if "/features/commands/" in path:
        return (
            "KEEP",
            stage,
            "Core durable record, RPC, output cursor or command business logic",
        )
    if "/diagnostics/" in path or "/observability/" in path:
        return (
            "KEEP",
            stage,
            "Portable diagnostic/reporting or telemetry parser; host collection is a distinct boundary",
        )
    return (
        "KEEP",
        stage,
        "No native OS mechanisms required; portable application logic or Python package marker",
    )


def generate(root: Path = ROOT) -> dict[str, Any]:
    os0 = json.loads(
        (
            root / "docs/os-independent-stage1-evidence/os0-source-inventory.json"
        ).read_text()
    )
    prior = {entry["path"]: entry for entry in os0["inventory"]}
    original = set(prior)
    policy = architecture.load_policy(root / "quality-policy.json")
    package = root / "src/binnacle"
    imports: dict[str, set[str]] = {}
    rows: list[dict[str, Any]] = []
    for name in code_paths(root):
        path = root / name
        text = path.read_text(encoding="utf-8")
        category, stage, rationale = classify(name, prior)
        if name.startswith("src/binnacle/"):
            mod = architecture.module_name(path, root / "src")
            targets = architecture.imports_of(path, mod)
            imports[mod] = targets
        else:
            mod = "scripts." + path.stem
            targets = architecture.imports_of(path, mod)
        rows.append(
            {
                "path": name,
                "sha256": hashlib.sha256(text.encode()).hexdigest(),
                "module": mod,
                "owner": category,
                "stage": stage,
                "rationale": rationale,
                "was_in_baseline": name in original,
                "original_owner": prior[name]["owner"] if name in prior else None,
                "imports": sorted(targets),
                "lexical_host_tokens": sorted(t for t in HOST_TOKENS if t in text),
            }
        )
    problems = architecture.evaluate(imports, policy) + inspect_source_tree(
        package, policy=policy, imports=imports
    )
    new = sorted({r["path"] for r in rows} - original)
    missing = sorted(original - {r["path"] for r in rows})
    return {
        "task_id": "BINNACLE-OS-STAGE1-IMPLEMENT-20261009",
        "baseline_commit": "02f4bab9bc7562668ffc41d622c4274449933768",
        "implementation_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip(),
        "production_module_count": sum(
            r["path"].startswith("src/binnacle/") for r in rows
        ),
        "script_count": sum(r["path"].startswith("scripts/") for r in rows),
        "classification_counts": dict(Counter(r["owner"] for r in rows)),
        "coverage_complete": len(rows) == len(code_paths(root)),
        "baseline_paths_added": new,
        "baseline_paths_missing": missing,
        "architecture_failures": problems,
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    payload = generate()
    dest = OUT / "os6-source-reconciliation.json"
    if args.check:
        if not dest.exists():
            raise SystemExit(f"missing checked inventory: {dest}")
        actual = json.loads(dest.read_text())
        # Candidate SHA is the only mutable field after committing an unchanged tree.
        for record in (payload, actual):
            record.pop("implementation_commit", None)
        if payload != actual:
            raise SystemExit(
                "OS6 inventory is stale; recapture source before signing review"
            )
    else:
        dest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(
        f"OS6: {payload['production_module_count']} production modules, "
        f"{payload['script_count']} scripts, "
        f"{len(payload['architecture_failures'])} architecture violations, "
        f"{len(payload['baseline_paths_added'])} new paths, "
        f"{len(payload['baseline_paths_missing'])} deleted paths"
    )
    for error in payload["architecture_failures"]:
        print("ERROR:", error)
    return int(bool(payload["architecture_failures"]))


if __name__ == "__main__":
    raise SystemExit(main())
