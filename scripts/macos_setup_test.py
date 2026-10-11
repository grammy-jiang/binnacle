"""Exercise the test-owned Darwin setup transaction and write a rollback receipt.

Uses a recording in-process lifecycle: no launchctl, no real launchd job and no
global state. Real launchd proof needs A3's lifecycle and is not claimed here.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

from binnacle.deployment.darwin import setup
from binnacle.deployment.darwin.provisioner import sha256_hex

LABEL = "com.binnacle.r3test.setup"


class RecordingLifecycle:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.loaded = False
        self.stuck = False

    def bootstrap(self, label: str, plist_path: Path) -> None:
        self.calls.append(f"bootstrap:{label}")
        self.loaded = True

    def bootout(self, label: str) -> None:
        self.calls.append(f"bootout:{label}")
        self.loaded = self.stuck

    def is_absent(self, label: str) -> bool:
        return not self.loaded


def _run(root: Path, lc: RecordingLifecycle, *cmd: str) -> int:
    base = ["--root", str(root), "--label", LABEL]
    extra = ["--exec", "/usr/bin/true"] if cmd[0] == "plan" else []
    with (
        contextlib.redirect_stdout(io.StringIO()),
        contextlib.redirect_stderr(io.StringIO()),
    ):
        return setup.main([cmd[0], *base, *extra], lifecycle=lc)


def scenario() -> dict[str, object]:
    out: dict[str, object] = {"label": LABEL, "full_parity": False}
    with tempfile.TemporaryDirectory(prefix="r3setup") as tmp:
        root = Path(tmp).resolve() / "root"
        root.mkdir(mode=0o700)
        plist = root / "LaunchAgents" / f"{LABEL}.plist"
        prior = b"prior-owned-bytes"
        plist.parent.mkdir(mode=0o700)
        plist.write_bytes(prior)
        lc = RecordingLifecycle()
        out["plan_rc"] = _run(root, lc, "plan")
        out["apply_rc"] = _run(root, lc, "apply")
        out["applied_differs_from_prior"] = plist.read_bytes() != prior
        out["rollback_rc"] = _run(root, lc, "rollback")
        out["prior_bytes_restored"] = plist.read_bytes() == prior
        out["prior_sha256"] = sha256_hex(prior)
        out["lifecycle_calls"] = lc.calls
        out["label_absent_after"] = lc.is_absent(LABEL)
        # Negative: teardown not verified -> rollback must fail and keep ownership.
        lc2 = RecordingLifecycle()
        _run(root, lc2, "plan")
        _run(root, lc2, "apply")
        lc2.stuck = True
        out["incomplete_rollback_rc"] = _run(root, lc2, "rollback")
        out["incomplete_rollback_plist_kept"] = plist.exists()
        lc2.stuck = False
        out["retry_rollback_rc"] = _run(root, lc2, "rollback")
        # Negative: foreign bytes appear -> preserved, nothing booted out.
        _run(root, lc2, "plan")
        _run(root, lc2, "apply")
        plist.write_bytes(b"foreign")
        before = len(lc2.calls)
        out["foreign_rollback_rc"] = _run(root, lc2, "rollback")
        out["foreign_preserved"] = plist.read_bytes() == b"foreign"
        out["foreign_no_bootout"] = len(lc2.calls) == before
        # Negative: non-test label refused.
        with contextlib.redirect_stderr(io.StringIO()):
            out["global_label_rc"] = setup.main(
                [
                    "plan",
                    "--root",
                    str(root),
                    "--label",
                    "com.apple.foo",
                    "--exec",
                    "/usr/bin/true",
                ],
                lifecycle=lc2,
            )
    out["ok"] = (
        out["plan_rc"] == 0
        and out["apply_rc"] == 0
        and out["rollback_rc"] == 0
        and out["prior_bytes_restored"] is True
        and out["incomplete_rollback_rc"] == 3
        and out["incomplete_rollback_plist_kept"] is True
        and out["retry_rollback_rc"] == 0
        and out["foreign_rollback_rc"] == 2
        and out["foreign_preserved"] is True
        and out["foreign_no_bootout"] is True
        and out["global_label_rc"] == 1
    )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--receipt", type=Path)
    ns = ap.parse_args()
    doc = scenario()
    doc["uid"] = os.getuid()
    doc["lifecycle"] = "in-process recording fake; real launchd UNAVAILABLE until A3"
    text = json.dumps(doc, indent=1, sort_keys=True)
    if ns.receipt:
        ns.receipt.write_text(text + "\n")
    print(text)
    return 0 if doc["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
