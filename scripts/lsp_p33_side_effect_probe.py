"""P3.3 opt-in native Pyright side-effect CHARACTERIZATION, not a sandbox.

The probe creates only synthetic source in a disposable host-controlled tree,
uses the actual Binnacle P2.4/P2.5 interfaces and pinned upstream multilspy,
and emits no parent environment values, source text, absolute paths or raw LSP.

It can be launched under a host syscall tracer, but captures only observed
behavior: inability to observe a write/network event is not OS enforcement.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import psutil

from binnacle.config_development_intelligence import (
    DevelopmentIntelligenceSettings,
    DevelopmentProviderSettings,
)
from binnacle.features.development_intelligence.lsp_document_sync import (
    AuthorizedDocumentSession,
)
from binnacle.features.development_intelligence.lsp_process_owner import (
    PrivatePyrightProcessOwner,
)
from binnacle.features.development_intelligence.lsp_workspace_access import (
    AuthorizedWorkspace,
)
from tests.fixtures.lsp.side_effects import Entry, manifest

_MARKER_NAME = "BINNACLE_P33_SYNTHETIC_SENTINEL_20261022"


def _contents(root: Path) -> dict[str, Entry]:
    """Full synthetic-tree manifest, including modes, ignored files and links."""
    return manifest(root)


async def characterize(binary: Path) -> dict[str, Any]:
    if not binary.is_absolute() or not binary.is_file():
        raise ValueError("audited binary is not an absolute local file")
    metadata = json.loads((binary.resolve().parent / "package.json").read_text())
    if metadata.get("name") != "pyright" or metadata.get("version") != "1.1.413":
        raise ValueError("audited provider identity is not Pyright 1.1.413")
    with tempfile.TemporaryDirectory(prefix="binnacle-p33-audit-") as temporary:
        audit = Path(temporary).resolve()
        approved = audit / "allowed"
        project = approved / "synthetic-repo"
        project.mkdir(parents=True)
        (project / ".git").write_text("gitdir: /synthetic-ignored\n", encoding="utf-8")
        (project / "lib.py").write_text(
            "def greet(name: str) -> str:\n    return name.upper()\n", encoding="utf-8"
        )
        source = project / "app.py"
        source.write_text(
            "from lib import greet\nanswer = greet('Ada')\n", encoding="utf-8"
        )
        home = audit / "synthetic-home"
        home.mkdir()
        for name in ("cache", "config", "data", "temp"):
            (audit / name).mkdir()
        # Only a synthetic marker is injected; no parent secret names/values
        # are read, stored in telemetry or printed.
        patched = {
            _MARKER_NAME: "binnacle-audit-fake-value-not-a-real-secret",
            "HOME": str(home),
            "XDG_CACHE_HOME": str(audit / "cache"),
            "XDG_CONFIG_HOME": str(audit / "config"),
            "XDG_DATA_HOME": str(audit / "data"),
            "TMPDIR": str(audit / "temp"),
        }
        before = _contents(audit)
        launch_seen: dict[str, Any] = {"provider_spawn_intercepted": False}
        from asyncio import create_subprocess_exec

        async def watch_spawn(*args: Any, **kwargs: Any) -> Any:
            if "--stdio" in args and str(binary.resolve()) in args:
                environment = kwargs.get("env")
                launch_seen["provider_spawn_intercepted"] = True
                launch_seen["synthetic_marker_forwarded"] = (
                    isinstance(environment, dict)
                    and environment.get(_MARKER_NAME) == patched[_MARKER_NAME]
                )
                # Record only a count, never the inherited env names or values.
                launch_seen["environment_entry_count"] = (
                    len(environment) if isinstance(environment, dict) else None
                )
            return await create_subprocess_exec(*args, **kwargs)

        settings = DevelopmentIntelligenceSettings(
            enabled=True,
            profiles={
                "pyright": DevelopmentProviderSettings(
                    enabled=True,
                    source="trusted_absolute",
                    executable=str(binary),
                    mode="explicit_trust_only",
                    languages=("python",),
                )
            },
        )
        workspace = AuthorizedWorkspace((approved,), source)
        owner = PrivatePyrightProcessOwner(
            settings, workspace.workspace_root, operator_allowed_roots=(approved,)
        )
        maximum_children = 0
        connections_observed = 0
        sockets_observable = True
        samples = 0

        async def sample_process_tree(pid: int, finished: asyncio.Event) -> None:
            nonlocal maximum_children, connections_observed, sockets_observable, samples
            while not finished.is_set():
                try:
                    parent = psutil.Process(pid)
                    observed = [parent, *parent.children(recursive=True)]
                    maximum_children = max(maximum_children, len(observed) - 1)
                    for process in observed:
                        try:
                            connections_observed += len(
                                process.net_connections(kind="inet")
                            )
                        except (psutil.AccessDenied, OSError):
                            sockets_observable = False
                    samples += 1
                except psutil.NoSuchProcess:
                    break
                await asyncio.sleep(0.04)

        monitor_task = None
        finish = asyncio.Event()
        try:
            with (
                patch.dict(os.environ, patched),
                patch("asyncio.create_subprocess_exec", new=watch_spawn),
            ):
                async with owner.session() as server:
                    process = server.server.process
                    if process is None:
                        raise RuntimeError("audit_provider_process_not_started")
                    monitor_task = asyncio.create_task(
                        sample_process_tree(process.pid, finish)
                    )
                    async with AuthorizedDocumentSession(
                        server, workspace
                    ) as documents:
                        result = await documents.definition(
                            "app.py", line=2, column=10, expected_symbol="greet"
                        )
                        if not result or result[0]["relativePath"] != "lib.py":
                            raise RuntimeError("audit_definition_query_failed")
                    # Allow process socket sampler to see an idle steady-state.
                    await asyncio.sleep(0.15)
        finally:
            finish.set()
            if monitor_task is not None:
                await asyncio.wait_for(monitor_task, timeout=3)
        after = _contents(audit)
        created = sorted(set(after) - set(before))
        changed = sorted(
            name for name in before.keys() & after.keys() if before[name] != after[name]
        )
        deleted = sorted(set(before) - set(after))
        evidence = owner.last_exit
        if evidence is None:
            raise RuntimeError("audit_provider_cleanup_evidence_missing")
        return {
            "platform": platform.system(),
            "provider": "multilspy.PyrightServer 1.1.413",
            "synthetic_marker_forwarded": launch_seen.get("synthetic_marker_forwarded"),
            "environment_mode": "p33_admitted_node_minimal_env",
            "provider_spawn_intercepted": launch_seen["provider_spawn_intercepted"],
            "environment_entry_count": launch_seen.get("environment_entry_count"),
            "synthetic_audit_files_created": created,
            "synthetic_audit_files_changed": changed,
            "synthetic_audit_files_deleted": deleted,
            "sockets_sampled": connections_observed,
            "network_sampling_complete": sockets_observable,
            "network_samples": samples,
            "max_child_processes_sampled": maximum_children,
            "clean_parent_exit": evidence.parent_exited,
            "cleanup_unverified": evidence.cleanup_unverified,
            "descendant_count_observed": len(evidence.observed_descendants),
            "scope": "synthetic_workspace_plus_synthetic_home_only",
            "read_eligibility": "NOT_PROVEN",
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Private P3.3 Pyright behavior audit")
    parser.add_argument("--binary", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = asyncio.run(asyncio.wait_for(characterize(args.binary), timeout=40))
    except (OSError, ValueError, RuntimeError, TimeoutError):
        print(json.dumps({"audit_status": "failed", "read_eligibility": "NOT_PROVEN"}))
        return 1
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
