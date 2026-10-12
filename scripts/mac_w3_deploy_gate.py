#!/usr/bin/env python3
"""R6 W3 delta adapter for the independently reviewed J7m-a5 Mac deploy gate.

The base deployment gate remains immutable. It is loaded only after a strict
SHA-256 verification and the two E1-a4 production health deltas are added.
This wrapper never grants deployment approval: all original J7m guards,
exact-SHA CI, quiet-window, jobs-owner, smoke, and rollback logic still run.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

BASE_SHA256 = "cad6ac5aa4a4ed65ad54e6c34b2a82867d7208f8f2591aaf167551cd83fca343"
BASE_RELATIVE = (
    "Projects/binnacle-macos-native-20261011/state/r3-20261011-01/"
    "jobs/R6W2-J7m-a5/mac_deploy_gate.py"
)
DOCTOR_TIMEOUT_SECONDS = 45.0


def verified_gate(path: Path) -> ModuleType:
    """Only the reviewed, pinned gate is eligible to make production changes."""
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != BASE_SHA256:
        raise ValueError("J7m-W3 base deployment gate hash mismatch; refusing")
    spec = importlib.util.spec_from_file_location("_binnacle_mac_j7m_a5", path)
    if spec is None or spec.loader is None:
        raise ValueError("cannot load verified base deployment gate")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_startup_doctor(text: str) -> tuple[bool, str, list[str]]:
    """Ignore unrelated doctor status; fail CLOSED if startup status is absent."""
    try:
        # The reviewed base runner combines stdout and stderr. Doctor JSON
        # is emitted on stdout first; harmless stderr diagnostics may follow.
        # Only accept a complete JSON object starting at the first byte.
        raw, consumed = json.JSONDecoder().raw_decode(text.lstrip())
        _tail = text.lstrip()[consumed:]
        if _tail.strip() and not _tail.lstrip().startswith(
            ("WARN", "WARNING", "INFO", "ERROR")
        ):
            raise ValueError("unexpected trailing doctor output")
        rows = raw["checks"]
        if not isinstance(rows, list):
            raise TypeError("checks is not an array")
        startup = [
            item
            for item in rows
            if isinstance(item, dict) and item.get("group") == "startup"
        ]
        if not startup:
            return False, "startup_check_missing", []
        if any(item.get("status") not in ("ok", "warn", "fail") for item in startup):
            return False, "startup_check_invalid", []
        failures = [
            str(item.get("detail", ""))[:500]
            for item in startup
            if item.get("status") == "fail"
        ]
        return not failures, ("startup_failure" if failures else "startup_ok"), failures
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return False, "startup_doctor_unparseable", []


def add_w3_checks(gate_module: Any) -> None:
    """Source-compatible extension of only the original Gate and reason table."""
    gate = gate_module.Gate
    original_step_smoke = gate.step_smoke
    gate_module.FAIL_REASONS = (
        ("startup_import_failed", "event=startup_import_failed"),
        *gate_module.FAIL_REASONS,
    )
    gate_module.FAIL_EXIT_REASONS = {
        **gate_module.FAIL_EXIT_REASONS,
        70: "EX_STARTUP_IMPORT",
    }

    def step_smoke(
        self: Any, name: str, expect_sha: str, via_manager: bool = False
    ) -> bool:
        passed: bool = original_step_smoke(
            self, name, expect_sha, via_manager=via_manager
        )
        if not passed or not name.startswith("7"):
            # Preserve the exact base gate's rollback smoke and failures.
            return passed
        interpreter = self.a.checkout / ".venv" / "bin" / "binnacle"
        rc, body = self.run(
            [str(interpreter), "doctor", "--json"],
            DOCTOR_TIMEOUT_SECONDS,
            cwd=str(self.a.checkout),
        )
        clean, reason, failures = parse_startup_doctor(body)
        # Doctor may fail unrelated systemd/unit checks; the existing gate's
        # authenticated live smoke owns endpoint/manager safety.
        result: bool = self.step(
            "7a_startup_doctor",
            clean,
            reason=reason,
            doctor_rc=rc,
            startup_failures=failures,
        )
        return result

    gate.step_smoke = step_smoke


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--w3-base-gate",
        type=Path,
        default=Path.home() / BASE_RELATIVE,
    )
    base_args, remaining = parser.parse_known_args(argv)
    try:
        original = verified_gate(base_args.w3_base_gate)
        add_w3_checks(original)
    except (OSError, ValueError) as exc:
        print(f"J7m-W3 refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    return int(original.main(remaining))


if __name__ == "__main__":
    raise SystemExit(main())
