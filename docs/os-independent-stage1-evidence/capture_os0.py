"""Read-only, reproducible v1.0.1 OS0 tracked-source and dependency inventory."""

import ast
import hashlib
import json
import re
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
BASE = "02f4bab9bc7562668ffc41d622c4274449933768"
SEAMS = {
    "src/binnacle/server.py": (
        "SPLIT",
        "OS2",
        "Pure native FastMCP application factory separated from Linux bootstrap",
        "OI-03, OI-05, FM-01, FM-08",
    ),
    "src/binnacle/config.py": (
        "SPLIT",
        "OS2",
        "Host runtime defaults selected at composition, not generic settings",
        "OI-05",
    ),
    "src/binnacle/cli.py": (
        "SPLIT",
        "OS4",
        "Generic dispatch vs host setup and systemd hints",
        "OI-09, OI-12",
    ),
    "src/binnacle/platform/job_platform.py": (
        "SPLIT",
        "OS2",
        "One explicit OS resolver with Linux default",
        "OI-03, OI-05",
    ),
    "src/binnacle/platform/deployment_platform.py": (
        "SPLIT",
        "OS2",
        "One explicit OS resolver with Linux default",
        "OI-03, OI-09",
    ),
    "src/binnacle/features/commands/jobs.py": (
        "SPLIT",
        "OS3",
        "Job policy/storage vs native identity, signaling, accounting",
        "OI-04, OI-06, OI-07",
    ),
    "src/binnacle/features/commands/job_manager.py": (
        "SPLIT",
        "OS3",
        "RPC/owner lifecycle vs Linux readiness notification",
        "OI-07",
    ),
    "src/binnacle/features/commands/job_owner.py": (
        "BOUNDARY",
        "OS3",
        "Validated scoped process identity and process stop",
        "OI-06, OI-07",
    ),
    "src/binnacle/features/commands/command_status.py": (
        "BOUNDARY",
        "OS3",
        "Generic identity query without breaking public Linux metadata",
        "OI-06, FM-08",
    ),
    "src/binnacle/features/commands/job_resource_history.py": (
        "BOUNDARY",
        "OS3",
        "Retention/finalization policy vs host containment",
        "OI-07",
    ),
    "src/binnacle/deployment/units.py": (
        "SPLIT",
        "OS4",
        "Generic plan/diff/markers vs Linux unit/proc/service mechanics",
        "OI-09, OI-12",
    ),
    "src/binnacle/diagnostics/doctor.py": (
        "SPLIT",
        "OS5",
        "Generic report aggregation vs host checks and hints",
        "OI-04, OI-09",
    ),
    "src/binnacle/diagnostics/doctor_common.py": (
        "BOUNDARY",
        "OS4",
        "No OS execution in generic helper",
        "OI-09",
    ),
    "src/binnacle/diagnostics/doctor_jobs.py": (
        "BOUNDARY",
        "OS5",
        "Host-neutral durable jobs diagnostics",
        "OI-04",
    ),
    "src/binnacle/diagnostics/job_manager_doctor.py": (
        "BOUNDARY",
        "OS5",
        "Host-neutral RPC and diagnostic errors",
        "OI-04",
    ),
    "src/binnacle/diagnostics/doctor_connectivity.py": (
        "BOUNDARY",
        "OS5",
        "Generic HTTP probe vs Linux remediation",
        "OI-09",
    ),
    "src/binnacle/observability/logstats.py": (
        "SPLIT",
        "OS5",
        "Pure parser/aggregation must not import journal facade",
        "OI-10",
    ),
    "src/binnacle/observability/logstats_io.py": (
        "BOUNDARY",
        "OS5",
        "Explicit Linux journal acquisition compatibility",
        "OI-10",
    ),
    "src/binnacle/observability/system_resource_history.py": (
        "BOUNDARY",
        "OS5",
        "Optional external history provider",
        "OI-04",
    ),
    "src/binnacle/observability/log_safety.py": (
        "BOUNDARY",
        "OS5",
        "Canonical paths and privacy-safe telemetry hash",
        "OI-08",
    ),
    "src/binnacle/features/files/paths.py": (
        "SPLIT",
        "OS5",
        "Canonicalized roots + candidates with no traversal",
        "OI-08",
    ),
    "src/binnacle/platform/contracts/process_contracts.py": (
        "BOUNDARY",
        "OS1",
        "Opaque job process identity and owned signal targets",
        "OI-06",
    ),
    "src/binnacle/platform/contracts/resource_contracts.py": (
        "BOUNDARY",
        "OS1",
        "Semantic containment and resource snapshot protocols",
        "OI-07",
    ),
    "src/binnacle/platform/contracts/runtime_path_contracts.py": (
        "BOUNDARY",
        "OS1",
        "Stable host path value contract",
        "OI-05",
    ),
    "src/binnacle/platform/contracts/service_lifecycle_contracts.py": (
        "BOUNDARY",
        "OS1",
        "Managed services capability and error semantics",
        "OI-09",
    ),
    "src/binnacle/platform/contracts/service_log_contracts.py": (
        "BOUNDARY",
        "OS1",
        "Service logs acquisition interface",
        "OI-10",
    ),
}
HOST_MARKERS = {
    "systemctl": r"\bsystemctl\b",
    "journalctl": r"\bjournalctl\b",
    "loginctl": r"\bloginctl\b",
    "procfs": r"['\"](?:/proc/|/proc\b)",
    "cgroup": r"/sys/fs/cgroup|\bcgroup\b",
    "linux_import": r"(?:binnacle\.platform\.linux|binnacle\.observability\.linux)",
    "native_signals": r"\b(?:os\.kill|os\.killpg|signal\.SIGTERM|signal\.SIGKILL)\b",
    "systemd_notify": r"NOTIFY_SOCKET|READY=1",
    "native_subprocess": r"\b(?:subprocess\.Popen|subprocess\.run|subprocess\.check_output)\b",
    "host_detection": r"\b(?:sys\.platform|platform\.system|os\.uname)\b",
}


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


if git("rev-parse", f"{BASE}^{{commit}}") != BASE:
    raise RuntimeError("baseline commit cannot be resolved")
if git("diff", "--name-only", BASE, "HEAD", "--", "src/", "scripts/", "tests/"):
    raise RuntimeError("production code changed relative to baseline")
paths = git("ls-files", "-z").split("\0")
paths = [s for s in paths if s]
manifest = {}
inventory = []
all_imports = []
for name in paths:
    path = ROOT / name
    if not path.is_file() or path.is_symlink():
        continue
    buf = path.read_bytes()
    manifest[name] = hashlib.sha256(buf).hexdigest()
    if not (name.endswith(".py") and (name.startswith(("src/binnacle/", "scripts/")))):
        continue
    source = buf.decode("utf-8")
    try:
        tree = ast.parse(source, filename=name)
    except SyntaxError as e:
        raise RuntimeError(f"{name}: {e}") from e
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports += [node.module]
        elif isinstance(node, ast.Call) and isinstance(
            node.func, (ast.Name, ast.Attribute)
        ):
            func = ast.unparse(node.func)
            if (
                func in {"__import__", "importlib.import_module"}
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                imports.append("dynamic:" + node.args[0].value)
    hits = [k for k, regex in HOST_MARKERS.items() if re.search(regex, source)]
    if name in SEAMS:
        kind, stage, rationale, checks = SEAMS[name]
    elif name.startswith(
        ("src/binnacle/platform/linux/", "src/binnacle/observability/linux/")
    ):
        kind, stage, rationale, checks = (
            "LINUX",
            "OS6",
            "Native Linux adapter kept outside core",
            "OI-01, OI-12",
        )
    elif name.startswith(("src/binnacle/companions/",)):
        kind, stage, rationale, checks = (
            "LINUX",
            "OS6",
            "Independent Linux/Pi companion, no reverse dependency",
            "OI-11",
        )
    elif name in {
        "src/binnacle/deployment/server_unit.py",
        "src/binnacle/deployment/job_manager_unit.py",
    }:
        kind, stage, rationale, checks = (
            "LINUX",
            "OS4",
            "Explicit Linux systemd unit template",
            "OI-09, OI-12",
        )
    elif name.startswith("scripts/"):
        if any(
            h in hits
            for h in (
                "systemctl",
                "journalctl",
                "loginctl",
                "procfs",
                "cgroup",
                "linux_import",
                "host_detection",
                "systemd_notify",
            )
        ):
            kind, stage, rationale, checks = (
                "LINUX",
                "OS6",
                "Host-dependent maintenance/deployment tooling; classify and isolate",
                "OI-01, OI-12",
            )
        else:
            kind, stage, rationale, checks = (
                "KEEP",
                "OS6",
                "Portable external tooling; subprocess for Git/test/rg is not inherently Linux",
                "OI-01",
            )
    elif any(
        h in hits
        for h in (
            "systemctl",
            "journalctl",
            "loginctl",
            "procfs",
            "linux_import",
            "native_signals",
            "systemd_notify",
        )
    ):
        kind, stage, rationale, checks = (
            "BOUNDARY",
            "OS6",
            "Explicit host mechanism reference requires separation audit",
            "OI-01",
        )
    else:
        kind, stage, rationale, checks = (
            "KEEP",
            "OS6",
            "Domain logic or native FastMCP glue; no direct platform mechanism observed",
            "OI-01, FM-07",
        )
    entry = {
        "path": name,
        "sha256": manifest[name],
        "owner": kind,
        "work_package": stage,
        "rationale": rationale,
        "gates": checks,
        "observed_os_markers": hits,
        "imports": sorted(set(imports)),
    }
    inventory.append(entry)
    all_imports.extend((name, target) for target in imports)
snapshot = {
    "task_id": "BINNACLE-OS-STAGE1-IMPLEMENT-20261009",
    "baseline_sha": BASE,
    "inventory_source": "git tracked paths unchanged from exact baseline",
    "source_count": sum(x["path"].startswith("src/binnacle/") for x in inventory),
    "scripts_count": sum(x["path"].startswith("scripts/") for x in inventory),
    "classification_counts": dict(Counter(x["owner"] for x in inventory)),
    "tracked_file_manifest": "os0-manifest.sha256",
    "inventory": inventory,
    "import_edges": all_imports,
    "known_baseline_defects": [
        "Symlink allowed-root canonicalization falsely rejects canonical target",
        "Linux import-blocking cannot currently import pure server/jobs/logstats",
    ],
}
(OUT / "os0-source-inventory.json").write_text(
    json.dumps(snapshot, indent=2, sort_keys=True) + "\n"
)
(OUT / "os0-manifest.sha256").write_text(
    "".join(f"{manifest[k]}  {k}\n" for k in sorted(manifest))
)
risk = """# OS0 risk, interfaces, and dependent proofs

Source: exact v1.0.1 02f4bab9bc7562668ffc41d622c4274449933768.
The full per-file KEEP/SPLIT/LINUX/BOUNDARY map and every import edge is in os0-source-inventory.json.

| Priority | Contract/observable invariant | Implementation owner | Verification |
|---|---|---|---|
| P0 | FastMCP three mounts, eight tools, four wire profiles | OS2 | OI-03, OI-05, FM-01–FM-08 |
| P0 | Process identity checks before signal, durable RPC/records stable | OS1 + OS3 | OI-06, OI-07 |
| P0 | CLI, systemd unit bytes, no surprise restart | OS4 | OI-09, OI-12 |
| P0 | Root aliases allowed, escaping symlinks denied | OS5 | OI-08 |
| P1 | Log analytics independent of service_journal | OS5 | OI-10 |
| P1 | Linux-only script and companion direction | OS6 | OI-01, OI-11 |
| P1 | No eager Linux adapter activation in importable business core | OS2 + OS3 | OI-03–OI-05 |
| P1 | Linux metadata retained including pid, pgid, starttime, resource history | OS3 | OI-07, OI-12 |

Dependency order: OS0 -> OS1 reviewed contracts -> OS2 pure composition -> OS3 / OS4 and OS5 path -> OS5 diagnostics -> OS6 -> OS7.

Immutable snapshots are OS0 evidence, not new goldens or permission to rewrite existing wire pins.
"""
(OUT / "os0-risk-register.md").write_text(risk)
stamp = datetime.now(timezone.utc).isoformat()
ledger = {
    "task_id": "BINNACLE-OS-STAGE1-IMPLEMENT-20261009",
    "baseline_sha": BASE,
    "plan_sha": "19a3cf1e43755ed4aee3837c25ea63188058a26e",
    "candidate_sha": git("rev-parse", "HEAD"),
    "worktree_path": str(ROOT),
    "branch": git("branch", "--show-current"),
    "stage": "OS0",
    "status": "RUNNING",
    "updated_utc": stamp,
    "owner": "single ChatGPT implementation integrator",
    "completed": [
        "Plan read in full, 517 lines; repository instructions read",
        "Independent canonical worktree bootstrapped with locked uv 0.12.24",
        "Full tracked-source SHA-256 and per-module ownership/import inventory",
    ],
    "evidence": [
        "docs/os-independent-stage1-evidence/os0-source-inventory.json",
        "docs/os-independent-stage1-evidence/os0-manifest.sha256",
        "docs/os-independent-stage1-evidence/os0-risk-register.md",
    ],
    "tests": [],
    "reviews": [],
    "known_baseline_defects": snapshot["known_baseline_defects"],
    "review_status": "NOT_REQUESTED",
    "ci_status": "NOT_SUBMITTED",
    "deployment_status": "NOT_STARTED",
    "active_jobs": [],
    "next_action": "Capture raw FastMCP baseline, CLI and durable-process focused tests; then OS1",
}
(OUT / "ledger.json").write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n")
print(
    json.dumps(
        {
            "source_count": snapshot["source_count"],
            "scripts_count": snapshot["scripts_count"],
            "counts": snapshot["classification_counts"],
            "tracked_files": len(manifest),
            "manifest_sha256": hashlib.sha256(
                (OUT / "os0-manifest.sha256").read_bytes()
            ).hexdigest(),
        },
        indent=2,
    )
)
