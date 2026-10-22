"""Measurement bindings to P2.4/P2.5/P2.6 and pinned upstream; no LSP adapter."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import subprocess
import time
from importlib.metadata import distribution
from pathlib import Path
from typing import Any

from .corpus import Case
from .metrics import correct

UPSTREAM_SHA = "08ba0dbe60b6e0a3eff4796cb77ff5c0837bc892"
CAPABILITIES = {
    "manager_definition": "definitionProvider",
    "definition": "definitionProvider",
    "references": "referencesProvider",
    "hover": "hoverProvider",
    "document_symbols": "documentSymbolProvider",
    "workspace_symbols": "workspaceSymbolProvider",
}


def provenance(binary: Path) -> dict:
    """No executable discovery, installs, arbitrary version commands or raw paths."""
    if not binary.is_absolute():
        raise ValueError("absolute_trusted_binary_required")
    resolved = binary.resolve(strict=True)
    # Supported, preinstalled npm layout. A launcher digest alone is insufficient.
    package = resolved.parent
    manifest = package / "package.json"
    info = json.loads(manifest.read_text())
    if info.get("name") != "pyright" or info.get("version") != "1.1.413":
        raise ValueError("pyright_version_mismatch")
    upstream = distribution("multilspy")
    source = json.loads(upstream.read_text("direct_url.json") or "{}")
    if (
        source.get("url") != "https://github.com/grammy-jiang/multilspy.git"
        or source.get("vcs_info", {}).get("commit_id") != UPSTREAM_SHA
    ):
        raise ValueError("multilspy_provenance_mismatch")
    hashes = {}
    for name in (
        resolved.name,
        "package.json",
        "dist/pyright.js",
        "dist/pyright-internal.js",
        "dist/vendor.js",
    ):
        path = package / name
        if not path.is_file():
            raise ValueError("pyright_package_incomplete")
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    # The private owner executes the explicitly selected launcher's sibling
    # node, NEVER whichever executable happens to be first on inherited PATH.
    # Hash and version the same resolved runtime selected for launch.
    node_alias = binary.parent / "node"
    if not node_alias.is_file():
        raise ValueError("node_runtime_unavailable")
    node = node_alias.resolve(strict=True)
    node_version = subprocess.run(
        [str(node), "--version"], capture_output=True, text=True, check=True, timeout=5
    ).stdout.strip()
    if not re.fullmatch(r"v\d+\.\d+\.\d+", node_version):
        raise ValueError("node_version_unrecognized")
    template = Path(
        str(
            upstream.locate_file(
                "multilspy/language_servers/pyright_language_server/initialize_params.json"
            )
        )
    )
    return {
        "provider": "pyright",
        "version": "1.1.413",
        "source": "explicit_preinstalled_npm",
        "artifact_sha256": hashes,
        "multilspy_commit": UPSTREAM_SHA,
        "initialize_template_sha256": hashlib.sha256(template.read_bytes()).hexdigest(),
        "node_version": node_version,
        "node_executable_sha256": hashlib.sha256(node.read_bytes()).hexdigest(),
        "command": ["<trusted-pyright-langserver>", "--stdio"],
        "trust": "explicit_trust_only",
        "read_release": "NO_GO",
    }


async def await_workspace_symbol_readiness(
    query, is_correct, *, deadline_s: float, interval_s: float = 0.1
) -> int:
    """Wait for correct indexed gold, not just an advertised LSP capability.

    Pyright can return a legitimate empty workspace-symbol result while its
    index is settling. Such attempts are NOT measured warm results, and a
    bounded failure remains a failed startup rather than fabricated latency.
    """
    deadline = time.monotonic() + min(deadline_s, 5.0)
    attempts = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise asyncio.TimeoutError("workspace_symbol_readiness_unverified")
        attempts += 1
        response = await asyncio.wait_for(query(), timeout=remaining)
        if is_correct(response):
            return attempts
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise asyncio.TimeoutError("workspace_symbol_readiness_unverified")
        await asyncio.sleep(min(interval_s, remaining))


class NativeBackend:
    """One manager generation; known immutable snapshots only.

    Raw requests are measurement calls on that manager's owned upstream session.
    They are not a new production API and do not bypass into real repositories.
    """

    def __init__(
        self, binary: Path, roots: list[Path], concurrency: int, deadline: float
    ):
        from binnacle.config import RootsSettings
        from binnacle.config_development_intelligence import (
            DevelopmentIntelligenceSettings,
            DevelopmentProviderSettings,
        )
        from binnacle.features.development_intelligence.lsp_process_owner import (
            PrivatePyrightProcessOwner,
        )
        from binnacle.features.development_intelligence.lsp_provider_manager import (
            PrivateProviderManager,
        )

        self.roots = roots
        self.servers: dict[Path, Any] = {}
        self.owners: list[Any] = []
        self.initialization: list[float] = []
        self.readiness: list[dict[str, int | str]] = []
        self._readiness_timeout = float(deadline)
        self.capabilities: dict[Path, dict] = {}
        self.locks = [asyncio.Lock() for _ in roots]
        self.positions: dict[tuple[int, Case], int] = {}

        def owner_factory(*args, **kwargs):
            owner = PrivatePyrightProcessOwner(*args, **kwargs)
            original = owner._make_upstream_server

            def observed_server():
                server = original()
                root = Path(server.repository_root_path)
                self.servers[root] = server
                initialize = server.server.send.initialize

                async def observed_initialize(params):
                    started = time.perf_counter()
                    response = await initialize(params)
                    self.initialization.append((time.perf_counter() - started) * 1000)
                    self.capabilities[root] = response.get("capabilities", {})
                    return response

                server.server.send.initialize = observed_initialize
                return server

            owner._make_upstream_server = observed_server
            self.owners.append(owner)
            return owner

        settings = DevelopmentIntelligenceSettings(
            enabled=True,
            max_resident_servers=len(roots),
            request_timeout_s=deadline,
            idle_timeout_s=3600,
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
        self.manager = PrivateProviderManager(
            settings,
            RootsSettings(default_root=roots[0].parent, extra_roots=()),
            startup_timeout_s=deadline,
            queue_timeout_s=deadline,
            max_pending_requests=concurrency,
            max_parallel_requests=concurrency,
            _owner_factory=owner_factory,
        )

    async def start(self, cases: tuple[Case, ...]) -> None:
        # Sequential cold starts bound host pressure. The first gold definition
        # is part of startup-to-first-result, not a warm latency observation.
        for index in range(len(self.roots)):
            for case in cases:
                # Case anchors use Python codepoints, as P2.5 does. Convert
                # only direct upstream requests to LSP UTF-16 units.
                text = (self.roots[index] / case.file).read_text(encoding="utf-8")
                line = re.split(r"\r\n|\r|\n", text)[case.line]
                self.positions[index, case] = (
                    len(line[: case.character].encode("utf-16-le")) // 2
                )
            cold_result = await self.query(index, cases[0])
            if not correct(cases[0], cold_result, self.roots[index]):
                raise ValueError("cold_definition_gold_failed")
            # Some providers advertise workspace symbols before indexing has
            # completed. Confirm exact synthetic gold before timed warm calls.
            for case in cases:
                if case.operation != "workspace_symbols" or not self.supports(
                    index, case.operation
                ):
                    continue
                attempts = await await_workspace_symbol_readiness(
                    lambda index=index, case=case: self.query(index, case),
                    lambda value, index=index, case=case: correct(
                        case, value, self.roots[index]
                    ),
                    deadline_s=self._readiness_timeout,
                )
                self.readiness.append(
                    {"operation": "workspace_symbols", "attempts": attempts}
                )

    def supports(self, index: int, operation: str) -> bool:
        capability = self.capabilities.get(self.roots[index], {}).get(
            CAPABILITIES[operation]
        )
        return capability is True or isinstance(capability, dict)

    async def query(self, index: int, case: Case):
        root = self.roots[index]
        async with self.locks[index]:
            if case.operation == "manager_definition":
                return await self.manager.definition(
                    root / case.file,
                    line=case.line + 1,
                    column=case.character + 1,
                    expected_symbol=case.symbol,
                )
            server = self.servers[root]
            if case.operation == "workspace_symbols":
                return await server.server.send.workspace_symbol({"query": case.symbol})
            params: dict[str, Any] = {
                "textDocument": {"uri": (root / case.file).as_uri()}
            }
            if case.operation != "document_symbols":
                params["position"] = {
                    "line": case.line,
                    "character": self.positions[index, case],
                }
            if case.operation == "references":
                params["context"] = {"includeDeclaration": True}
            method = (
                "document_symbol"
                if case.operation == "document_symbols"
                else case.operation
            )
            return await getattr(server.server.send, method)(params)

    def processes(self) -> list[int]:
        return [
            server.server.process.pid
            for server in self.servers.values()
            if server.server.process is not None
            and server.server.process.returncode is None
        ]

    @property
    def residents(self) -> int:
        return self.manager.resident_count

    async def close(self) -> bool:
        receipt = await self.manager.aclose()
        return (
            not receipt.cleanup_unverified
            and receipt.instances_requested == receipt.instances_stopped
        )
