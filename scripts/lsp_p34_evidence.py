"""Sanitized identity and capability evidence for synthetic QA only."""

from __future__ import annotations

import hashlib
import importlib.metadata
import inspect
import json
import re
import struct
import subprocess
from pathlib import Path
from unittest.mock import patch

CAPABILITIES = (
    "definitionProvider",
    "declarationProvider",
    "referencesProvider",
    "hoverProvider",
    "documentSymbolProvider",
    "workspaceSymbolProvider",
    "typeDefinitionProvider",
    "implementationProvider",
    "callHierarchyProvider",
    "diagnosticProvider",
    "completionProvider",
    "signatureHelpProvider",
    "renameProvider",
    "codeActionProvider",
    "documentFormattingProvider",
    "semanticTokensProvider",
    "inlayHintProvider",
)


def digest(path):
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            hasher.update(block)
    return hasher.hexdigest()


def shape(value, depth=0):
    """Snapshot types/options without exporting any server-controlled strings.

    Standard keys are allowlisted; extension keys and all strings are redacted.
    No log, error text, raw URI, private path or hash of private settings escapes.
    """
    keys = set(CAPABILITIES) | {
        "textDocumentSync",
        "positionEncoding",
        "workspace",
        "workspaceFolders",
        "supported",
        "changeNotifications",
        "openClose",
        "change",
        "save",
        "includeText",
        "resolveProvider",
        "triggerCharacters",
        "allCommitCharacters",
        "workDoneProgress",
        "prepareProvider",
        "completionItem",
        "labelDetailsSupport",
        "interFileDependencies",
        "workspaceDiagnostics",
        "legend",
        "tokenTypes",
        "tokenModifiers",
        "range",
        "full",
        "delta",
        "commands",
        "executeCommandProvider",
        "codeActionKinds",
        "experimental",
        "documentLinkProvider",
        "colorProvider",
        "foldingRangeProvider",
        "selectionRangeProvider",
    }
    if depth > 12:
        return "<depth-limit>"
    if isinstance(value, dict):
        result = {
            key: shape(item, depth + 1) for key, item in value.items() if key in keys
        }
        if any(key not in keys for key in value):
            result["redacted_extension_count"] = sum(key not in keys for key in value)
        return result
    if isinstance(value, list):
        return [shape(item, depth + 1) for item in value[:128]]
    if isinstance(value, str):
        return "<string>"
    if value is None or type(value) in {bool, int, float}:
        return value
    return "<redacted>"


def advertised(capabilities, name):
    value = capabilities.get(name)
    return value is True or isinstance(value, dict)


def identity(binary):
    """Hash executable bytes and adjacent package metadata, not private paths."""
    result = {"executable_sha256": digest(binary), "version": "unknown"}
    for parent in list(binary.resolve().parents)[:4]:
        manifest = parent / "package.json"
        if manifest.is_file():
            package = json.loads(manifest.read_text())
            version = package.get("version", "")
            if re.fullmatch(r"[0-9][0-9A-Za-z.+-]{0,79}", version):
                result.update(
                    version=version,
                    version_source="package.json",
                    package_manifest_sha256=digest(manifest),
                )
                break
    return result


def adapter_probe(case, binary, root):
    """Use pinned upstream factory with explicit binary; never call start_server.

    The direct session below discovers current capabilities under restricted
    settings. Existing adapter defaults/assertions are not a safety profile.
    """
    if not case.adapter_language:
        return {"status": "no_upstream_adapter"}
    try:
        from multilspy import LanguageServer  # type: ignore[import-untyped]
        from multilspy.multilspy_config import (  # type: ignore[import-untyped]
            Language,
            MultilspyConfig,
        )
        from multilspy.multilspy_logger import (  # type: ignore[import-untyped]
            MultilspyLogger,
        )
    except ImportError:
        return {"status": "dependency_unavailable"}
    distribution = importlib.metadata.distribution("multilspy")
    direct = json.loads(distribution.read_text("direct_url.json") or "{}")
    revision = direct.get("vcs_info", {}).get("commit_id")
    if revision != "08ba0dbe60b6e0a3eff4796cb77ff5c0837bc892":
        return {"status": "dependency_revision_unreviewed"}
    # Upstream TS import asks platform.architecture(), which otherwise invokes
    # the PATH-selected `file` helper. Supply this interpreter's pointer width.
    with patch(
        "platform.architecture", return_value=(f"{struct.calcsize('P') * 8}bit", "")
    ):
        adapter = LanguageServer.create(
            MultilspyConfig(
                code_language=Language(case.adapter_language), server_binary=str(binary)
            ),
            MultilspyLogger(),
            str(root),
        )
    source = Path(inspect.getfile(type(adapter)))
    template = source.with_name("initialize_params.json")
    return {
        "status": "constructor_pass_session_unprobed",
        "class": type(adapter).__name__,
        "distribution_version": distribution.version,
        "revision": revision,
        "adapter_source_sha256": digest(source),
        "initialize_template_sha256": digest(template),
    }


def command_version(binary, root, env):
    """Bounded version output; retain only a version token, never raw output."""
    from scripts.lsp_p34_wire import Peer, ProbeError

    peer = Peer([str(binary), "--version"], root, env, 3)
    try:
        while len(peer.buffer) <= 8192:
            try:
                peer._fill()
            except ProbeError as error:
                if str(error) != "stdout_eof":
                    return "unknown"
                if peer.process.wait(timeout=1) != 0:
                    return "unknown"
                match = re.search(
                    rb"(?<![0-9])(?:\d{4}-\d{2}-\d{2}|\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?)\b",
                    peer.buffer,
                )
                return match[0].decode() if match else "unknown"
        return "unknown"
    except subprocess.TimeoutExpired:
        return "unknown"
    finally:
        peer.close()
