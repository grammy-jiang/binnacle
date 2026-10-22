"""Opt-in native QA on disposable fixtures. Not shipped; P3.3 READ NO-GO.

Run: python -m scripts.lsp_p34_breadth --run-native --output report.json
No workspace argument, PATH discovery, provider downloads, or production imports.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from scripts.lsp_p34_evidence import (
    CAPABILITIES,
    adapter_probe,
    advertised,
    command_version,
    digest,
    identity,
    shape,
)
from scripts.lsp_p34_fixtures import CASES, definition_gold, fixture, options, settings
from scripts.lsp_p34_wire import Peer, ProbeError


def environment(base, bin_dir):
    env = {
        "PATH": str(base / "bin"),
        "HOME": str(base / "home"),
        "XDG_CACHE_HOME": str(base / "cache"),
        "XDG_CONFIG_HOME": str(base / "config"),
        "XDG_DATA_HOME": str(base / "data"),
        "TMPDIR": str(base / "tmp"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "CARGO_NET_OFFLINE": "true",
        "SHELLCHECK_PATH": "",
        "SHFMT_PATH": "",
        "EXPLAINSHELL_ENDPOINT": "",
    }
    for name in ("bin", "home", "cache", "config", "data", "tmp"):
        (base / name).mkdir()
    # Node is the only helper on PATH. No npm, shellcheck, shfmt, Cargo or compiler.
    node = bin_dir / "node"
    if node.is_file():
        (base / "bin" / "node").symlink_to(node)
    return env


def symbol_ok(value, case):
    """Require the expected symbol and a valid range covering its source name."""
    if not isinstance(value, list):
        return False
    lines = case.text.splitlines()
    for item in value:
        if not isinstance(item, dict):
            continue
        span = item.get(
            "selectionRange",
            item.get("range", item.get("location", {}).get("range", {})),
        )
        start, end = span.get("start", {}), span.get("end", {})
        line, char = start.get("line"), start.get("character")
        if (
            item.get("name") == case.symbol
            and type(line) is int
            and type(char) is int
            and 0 <= line < len(lines)
            and 0 <= char <= len(lines[line])
            and type(end.get("line")) is int
            and type(end.get("character")) is int
            and 0 <= end["line"] < len(lines)
            and 0 <= end["character"] <= len(lines[end["line"]])
            and (end["line"], end["character"]) >= (line, char + len(case.symbol))
            and case.symbol in lines[line][char:]
        ):
            return True
        if symbol_ok(item.get("children"), case):
            return True
    return False


def definition_ok(value, root, gold):
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return False
    for item in value:
        if not isinstance(item, dict):
            continue
        uri = item.get("uri", item.get("targetUri"))
        span = item.get("range", item.get("targetSelectionRange", {}))
        if uri == (root / gold[2]).as_uri() and span.get("start") == {
            "line": gold[3],
            "character": gold[4],
        }:
            return True
    return False


def session(peer, case, root, row, tsserver=None):
    config = settings(case)
    init_options = options(case, root)
    params = {
        "processId": os.getpid(),
        "rootUri": root.as_uri(),
        "workspaceFolders": [{"uri": root.as_uri(), "name": "synthetic"}],
        "capabilities": {
            "workspace": {"configuration": True, "workspaceFolders": True},
            "textDocument": {
                "documentSymbol": {"hierarchicalDocumentSymbolSupport": True}
            },
            "general": {"positionEncodings": ["utf-16"]},
        },
        "initializationOptions": init_options,
    }
    row["initialize_inputs"] = {
        "capabilities": params["capabilities"],
        "options": {**init_options},
        "settings": config,
    }
    if "detachedFiles" in row["initialize_inputs"]["options"]:
        row["initialize_inputs"]["options"]["detachedFiles"] = ["<fixture>/main.rs"]
    if tsserver is not None:
        params["initializationOptions"] = {
            **init_options,
            "tsserver": {**init_options["tsserver"], "path": str(tsserver)},
        }
        row["initialize_inputs"]["options"]["tsserver"] = {
            **init_options["tsserver"],
            "path": "<installed-typescript>/lib/tsserver.js",
        }
    result = peer.request("initialize", params, config)
    if not isinstance(result, dict) or not isinstance(result.get("capabilities"), dict):
        raise ProbeError("invalid_initialize_result")
    caps = result["capabilities"]
    row["initialize"] = "pass"
    row["capability_snapshot"] = shape(caps)
    row["advertised"] = [name for name in CAPABILITIES if advertised(caps, name)]
    row["not_advertised"] = [
        name for name in CAPABILITIES if not advertised(caps, name)
    ]
    info = result.get("serverInfo", {})
    version = info.get("version", "") if isinstance(info, dict) else ""
    if re.fullmatch(r"[0-9][0-9A-Za-z.()+ -]{0,79}", version):
        row["identity"].update(version=version, version_source="initialize.serverInfo")
    encoding = caps.get("positionEncoding", "utf-16")
    row["position_encoding"] = (
        encoding if encoding in {"utf-8", "utf-16", "utf-32"} else "unknown"
    )
    peer.notify("initialized")
    peer.notify("workspace/didChangeConfiguration", {"settings": config})
    uri = (root / case.filename).as_uri()
    peer.notify(
        "textDocument/didOpen",
        {
            "textDocument": {
                "uri": uri,
                "languageId": case.language,
                "version": 1,
                "text": case.text,
            }
        },
    )
    if case.key == "bash":
        peer.await_diagnostics(uri, config)
        row["readiness"] = "document_diagnostics_received_not_completeness_proof"
    if advertised(caps, "documentSymbolProvider"):
        value = peer.request(
            "textDocument/documentSymbol", {"textDocument": {"uri": uri}}, config
        )
        row["document_symbol"] = (
            "fixture_pass" if symbol_ok(value, case) else "failed_gold"
        )
    else:
        row["document_symbol"] = "not_advertised"
    gold = definition_gold(case)
    row["definition"] = "unprobed"
    if gold and advertised(caps, "definitionProvider"):
        value = peer.request(
            "textDocument/definition",
            {
                "textDocument": {"uri": uri},
                "position": {"line": gold[0], "character": gold[1]},
            },
            config,
        )
        row["definition"] = (
            "fixture_pass" if definition_ok(value, root, gold) else "failed_gold"
        )
    peer.notify("textDocument/didClose", {"textDocument": {"uri": uri}})
    if peer.request("shutdown", None, config) is not None:
        raise ProbeError("invalid_shutdown_result")
    row["shutdown"] = "pass"
    peer.notify("exit")
    try:
        code = peer.process.wait(
            timeout=min(5, max(0.001, peer.deadline - time.monotonic()))
        )
    except subprocess.TimeoutExpired as error:
        raise ProbeError("exit_deadline") from error
    row["exit"] = "pass" if code == 0 else "nonzero"


def probe(case, bin_dir, timeout):
    row = {
        "provider": case.key,
        "classification": "benchmark_only",
        "read_eligible": False,
        "status": "not_installed",
        "initialize": "unprobed",
        "shutdown": "unprobed",
    }
    binary = bin_dir / case.executable
    if case.key == "make":
        row["requested_executable"] = "make-language-server"
        row["alternate_make_ls"] = (
            "present_unreviewed_not_launched"
            if (bin_dir / "make-ls").is_file()
            else "not_installed"
        )
    if not binary.is_file():
        return row
    # Unknown make-ls implementations must not be launched with guessed arguments.
    if case.key == "make":
        row["status"] = "identity_review_required"
        return row
    peer = None
    with tempfile.TemporaryDirectory(prefix="binnacle-p34-") as temporary:
        base = Path(temporary)
        root = base / "project"
        root.mkdir()
        files = fixture(case, root)
        env = environment(base, bin_dir)
        row["fixture_sha256"] = hashlib.sha256(
            json.dumps(files, sort_keys=True).encode()
        ).hexdigest()
        row["argv"] = [case.executable, *case.args]
        try:
            row["identity"] = identity(binary)
            if row["identity"]["version"] == "unknown":
                row["identity"].update(
                    version=command_version(binary, root, env),
                    version_source="bounded_version_command",
                )
            node = bin_dir / "node"
            if case.executable.endswith("language-server") and node.is_file():
                row["node_identity"] = {
                    "sha256": digest(node),
                    "version": command_version(node, root, env),
                }
            row["adapter"] = adapter_probe(case, binary, root)
            peer = Peer([str(binary), *case.args], root, env, timeout)
            tsserver = None
            if case.key in {"typescript", "javascript"}:
                tsserver = binary.resolve().parents[2] / "typescript/lib/tsserver.js"
                if not tsserver.is_file():
                    raise ProbeError("typescript_runtime_unavailable")
                row["typescript_identity"] = identity(tsserver)
                payload = tsserver.with_name("_tsserver.js")
                if payload.is_file():
                    row["typescript_identity"]["payload_sha256"] = digest(payload)
            session(peer, case, root, row, tsserver)
            row["status"] = (
                "pass"
                if row["exit"] == "pass" and "failed_gold" not in row.values()
                else "failed"
            )
        except ProbeError as error:
            row.update(status="failed", failure=str(error))
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            IndexError,
            AssertionError,
            RecursionError,
            subprocess.SubprocessError,
        ):
            row.update(status="failed", failure="local_or_provider_error")
        finally:
            if peer:
                peer.close()
                row.update(
                    cleanup=peer.cleanup, reverse_requests_denied=peer.reverse_denied
                )
                if peer.cleanup == "cleanup_unverified":
                    row["status"] = "failed"
        row["fixture_files_unchanged"] = all(
            not (root / name).is_symlink()
            and (root / name).is_file()
            and (root / name).stat().st_size == len(content.encode())
            and (root / name).read_bytes() == content.encode()
            for name, content in files.items()
        )
        row["extra_workspace_entries"] = len(list(root.iterdir())) - len(files)
        # Protocol success is not an integrity success: reject even silent
        # provider side effects and profiles without a proven semantic gold.
        if row["status"] == "pass" and (
            not row["fixture_files_unchanged"]
            or row["extra_workspace_entries"] != 0
            or row.get("document_symbol") != "fixture_pass"
        ):
            row.update(status="failed", failure="fixture_integrity_or_gold_unproven")
    return row


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-native",
        action="store_true",
        help="Authorize installed providers on synthetic fixtures only",
    )
    parser.add_argument("--bin-dir", type=Path, default=Path.home() / ".local/bin")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument(
        "--provider", choices=[case.key for case in CASES], action="append"
    )
    args = parser.parse_args(argv)
    if not args.run_native:
        parser.error("native providers require --run-native")
    if (
        os.name != "posix"
        or not 1 <= args.timeout <= 120
        or not args.bin_dir.is_absolute()
    ):
        parser.error("requires POSIX, an absolute binary directory and timeout 1..120")
    rows = [
        probe(case, args.bin_dir, args.timeout)
        for case in CASES
        if not args.provider or case.key in args.provider
    ]
    report = {
        "schema": 1,
        "run_id": uuid4().hex,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "evidence": "opt-in native QA; synthetic; not shipped; P3.3 READ NO-GO",
        "baseline": "66697d2",
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "timeout_seconds_per_session": args.timeout,
        "limits": {
            "network_confinement": False,
            "escaped_descendants": "unverified",
            "service_path": "not_checked",
            "full_dependency_identity": "not_audited",
        },
        "script_sha256": {
            path.name: digest(path)
            for path in Path(__file__).parent.glob("lsp_p34_*.py")
        },
        "providers": rows,
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "cases": len(rows),
                "passed": sum(row["status"] == "pass" for row in rows),
                "not_installed": sum(row["status"] == "not_installed" for row in rows),
                "failed": sum(
                    row["status"] not in {"pass", "not_installed"} for row in rows
                ),
            }
        )
    )
    return int(any(row["status"] not in {"pass", "not_installed"} for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
