"""P1.6 fixture-only CLI audit. No production execution or normalization API."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from tests.fixtures.lsp.process_observer import ProcessObserver
from tests.fixtures.lsp.side_effects import differences, manifest

ANALYZER = Path(__file__).with_name("fake_analyzer.py")
OUTPUT_LIMIT = 8192


@dataclass
class Audit:
    status: str
    exit_code: int
    diagnostics: list
    changes: dict
    cleanup_verified: bool
    stdout_retained: int
    stderr_retained: int
    trace: Path
    elapsed: float
    child_pids: tuple[int, ...]

    @property
    def clean(self) -> bool:
        return (
            self.status == "complete"
            and not self.diagnostics
            and not any(self.changes.values())
            and self.cleanup_verified
            and not self.child_pids
        )


def audit(sandbox: Path, scenario: str, *, timeout: float = 2) -> Audit:
    """Audit all declared sandbox roots, including external cache, even on failure.

    A cache write remains a deviation; callers may explicitly approve its exact
    diff. No global filesystem safety or provider READ eligibility is implied.
    """
    roots = {name: sandbox / name for name in ("workspace", "external-cache")}
    before = {name: manifest(root) for name, root in roots.items()}
    peer = ProcessObserver(
        sandbox,
        fault="child" if scenario == "child" else "none",
        command=[
            str(ANALYZER),
            "--sandbox",
            str(sandbox),
            "--scenario",
            scenario,
        ],
    )
    output = bytearray()
    status = "invalid"
    diagnostics: list = []
    started = time.monotonic()
    process = peer.process
    if process is None:
        raise RuntimeError("synthetic audit process not started")
    try:
        with peer:
            deadline = started + timeout
            while True:
                if time.monotonic() >= deadline:
                    status = "timeout"
                    break
                # Synthetic child waits on the harness pipe; reap before EOF.
                if scenario == "child" and any(
                    e["event"] == "child-ready" for e in peer.events()
                ):
                    peer.close_children()
                chunk = peer.read_chunk(min(0.01, deadline - time.monotonic()))
                if chunk == b"":
                    process.wait(timeout=max(0.001, deadline - time.monotonic()))
                    status, diagnostics = classify(bytes(output), process.returncode)
                    break
                if chunk:
                    if len(output) + len(chunk) > OUTPUT_LIMIT:
                        status = "oversize"
                        break
                    output.extend(chunk)
    finally:
        # Always compare side effects, including malformed/partial/crash results.
        changes = {
            name: differences(before[name], manifest(root))
            for name, root in roots.items()
        }
    return Audit(
        status,
        process.returncode,
        diagnostics,
        changes,
        peer.cleanup_verified,
        len(output),
        len(peer.stderr_sample),
        peer.trace,
        time.monotonic() - started,
        tuple(e["pid"] for e in peer.events() if e["event"] == "child-ready"),
    )


def classify(output: bytes, exit_code: int) -> tuple[str, list]:
    if exit_code not in (0, 1):
        return "crash", []
    try:
        result = json.loads(output)
    except (ValueError, UnicodeDecodeError):
        return "invalid", []
    if not isinstance(result, dict):
        return "invalid", []
    diagnostics = result.get("diagnostics")
    if (
        type(result.get("complete")) is not bool
        or result.get("analyzed") != ["fixture.py"]
        or not isinstance(diagnostics, list)
        or any(not valid_diagnostic(item) for item in diagnostics)
        or (exit_code == 1 and not diagnostics)
    ):
        return "invalid", []
    return ("complete" if result["complete"] else "partial"), diagnostics


def valid_diagnostic(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    if (
        item.get("path") != "fixture.py"
        or item.get("severity") != "error"
        or not isinstance(item.get("message"), str)
        or not isinstance(item.get("code"), str)
    ):
        return False
    span = item.get("range")
    if not isinstance(span, dict):
        return False
    for key in ("start", "end"):
        point = span.get(key)
        if not isinstance(point, dict) or any(
            type(point.get(axis)) is not int or point[axis] < 0
            for axis in ("line", "character")
        ):
            return False
    return (span["start"]["line"], span["start"]["character"]) <= (
        span["end"]["line"],
        span["end"]["character"],
    )
