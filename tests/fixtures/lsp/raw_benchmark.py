"""Stdlib-only, TEST-ONLY raw stdio benchmark. Never runs a real provider.

Run from the checkout: python -m tests.fixtures.lsp.raw_benchmark --output
/private/tmp/run.json. Output must be outside the checkout in a temporary
location. Gold is frozen independently of the fake's response implementation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from tests.fixtures.lsp.process_observer import ProcessObserver

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MANIFEST = HERE / "benchmark_manifest.json"
MANIFEST_SHA256 = "66978314db53dc83fcbbf97e310ba3e7e1341b5681321e9d3e30d848862a8c28"
PROVIDER_FILES = (
    "fake_stdio_server.py",
    "lsp_dialogue.py",
    "lsp_payloads.py",
    "lsp_transport.py",
    "process_faults.py",
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def load_manifest(path: Path) -> dict:
    data = path.read_bytes()
    if digest(data) != MANIFEST_SHA256:
        raise ValueError("unrecognized manifest or missing/incorrect gold")
    return json.loads(data)


def percentiles(values: list[float]) -> dict:
    """Nearest-rank percentiles; no interpolation or successful empty sample."""
    if not values or any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("invalid latency samples")
    ordered = sorted(values)
    return {
        f"p{p}": ordered[math.ceil(len(values) * p / 100) - 1] for p in (50, 95, 99)
    }


def identity(manifest: dict, repetitions: int, deadline: float, fault: str) -> dict:
    files = {name: digest((HERE / name).read_bytes()) for name in PROVIDER_FILES}
    # Clear inherited Git overrides, including hook-provided local variables.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    revision = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        env=env,
        timeout=3,
        text=True,
    ).strip()
    harness = {
        p.name: digest(p.read_bytes())
        for p in (
            Path(__file__),
            HERE / "lsp_peer.py",
            HERE / "process_observer.py",
        )
    }
    return {
        "manifest_sha256": MANIFEST_SHA256,
        "provider": {
            "name": "binnacle-fake-lsp",
            "version": "0",
            "sources": files,
            "package_sha256": digest(canonical(files)),
        },
        "harness": harness,
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "python": {
            "version": sys.version,
            "executable": sys.executable,
            "sha256": digest(Path(sys.executable).read_bytes()),
        },
        "repo_revision": revision,
        "case": manifest["case"],
        "profile": manifest["profile"],
        "method": manifest["method"],
        "semantics": manifest["semantics"],
        "workspace_sha256": digest(canonical(manifest["workspace"])),
        "gold_sha256": digest(canonical(manifest["gold"])),
        "setup": manifest["setup"],
        "measurement": {
            "warm_requests": repetitions,
            "deadline_s": deadline,
            "fault": fault,
            "percentiles": "nearest-rank",
            "transport": "raw-stdio",
            "clock": "perf_counter_ns",
            "timing": "send-through-decoded-response; gold checked before admission",
        },
    }


def request(
    peer: ProcessObserver, method: str, number: int, params: dict, deadline: float
) -> tuple[dict, float]:
    start = time.perf_counter_ns()
    peer.send({"jsonrpc": "2.0", "id": number, "method": method, "params": params})
    response = peer.receive(deadline)
    elapsed = (time.perf_counter_ns() - start) / 1_000_000
    peer.validate_response(response, number)
    if (
        response.get("jsonrpc") != "2.0"
        or "error" in response
        or "result" not in response
    ):
        raise ValueError("invalid response envelope")
    return response, elapsed


def semantic(
    peer: ProcessObserver, manifest: dict, number: int, deadline: float
) -> dict:
    response, elapsed = request(
        peer, manifest["method"], number, manifest["params"], deadline
    )
    # Exact equality checks response shape, URI and the entire gold range.
    if canonical(response["result"]) != canonical(manifest["gold"]):
        raise ValueError("incorrect semantic result")
    return {
        "correct": True,
        "latency_ms": elapsed,
        "result_count": 1,
        "result_bytes": len(canonical(response["result"])),
    }


def output_path(path: Path) -> Path:
    path = path.resolve()
    roots = (Path(tempfile.gettempdir()).resolve(), Path("/tmp").resolve())
    if path.is_relative_to(ROOT) or not any(path.is_relative_to(r) for r in roots):
        raise ValueError(
            "artifact destination must be temporary and outside source tree"
        )
    return path


def run(
    output: Path,
    *,
    manifest_path: Path = MANIFEST,
    repetitions: int = 30,
    deadline: float = 1.0,
    fault: str = "none",
) -> dict:
    output = output_path(output)
    if not 30 <= repetitions <= 1000 or not 0.01 <= deadline <= 3:
        raise ValueError(
            "bounded run requires 30..1000 requests and 0.01..3 second deadline"
        )
    if fault not in ("none", "crash-initialize", "hang-initialize", "crash-request"):
        raise ValueError("only explicit fake fault cases are permitted")
    artifact = {
        "schema": "binnacle-fake-raw-benchmark/1",
        "evidence": "fake-only",
        "valid": False,
        "gold_verified": False,
        "samples": [],
        "resources": {"status": "skipped"},
        "settling": {"status": "unobserved", "indexed": None},
    }
    try:
        manifest = load_manifest(manifest_path)
        artifact["identity"] = identity(manifest, repetitions, deadline, fault)
        with tempfile.TemporaryDirectory(prefix="binnacle-fake-bench-") as directory:
            workspace = Path(directory)
            for name, content in manifest["workspace"].items():
                (workspace / name).write_text(content, encoding="utf-8")
            start = time.perf_counter_ns()
            with ProcessObserver(workspace, fault, cwd=workspace) as peer:
                artifact["execution"] = {
                    "argv": peer.process.args,
                    "cwd": directory,
                    "pid": peer.process.pid,
                    "rootUri": workspace.as_uri(),
                }
                init, _ = request(
                    peer,
                    "initialize",
                    1,
                    {
                        "processId": None,
                        "rootUri": workspace.as_uri(),
                        "capabilities": {},
                        "initializationOptions": None,
                    },
                    deadline,
                )
                if (
                    init["result"].get("serverInfo")
                    != {"name": "binnacle-fake-lsp", "version": "0"}
                    or init["result"].get("capabilities", {}).get("definitionProvider")
                    is not True
                ):
                    raise ValueError("invalid initialize response")
                artifact["cold_initialize_ms"] = (
                    time.perf_counter_ns() - start
                ) / 1_000_000
                peer.send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
                artifact["first_request"] = semantic(peer, manifest, 2, deadline)
                for index in range(repetitions):
                    artifact["samples"].append(
                        semantic(peer, manifest, index + 3, deadline)
                    )
                peer.finish()
            artifact["cleanup_verified"] = peer.cleanup_verified
        artifact["warm_ms"] = percentiles(
            [s["latency_ms"] for s in artifact["samples"]]
        )
        artifact["correct_samples"] = len(artifact["samples"])
        artifact["gold_verified"] = True
        artifact["valid"] = True
    except (
        OSError,
        ValueError,
        TimeoutError,
        EOFError,
        AssertionError,
        subprocess.SubprocessError,
    ) as error:
        # Fixed error category only: never include response bodies, source or logs.
        artifact["failure"] = type(error).__name__
        artifact["correct_samples"] = len(artifact["samples"])
    with output.open("x", encoding="utf-8") as stream:
        json.dump(artifact, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--repetitions", type=int, default=30)
    args = parser.parse_args()
    artifact = run(
        args.output, manifest_path=args.manifest, repetitions=args.repetitions
    )
    return 0 if artifact["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
