"""Test-only unprivileged plan/apply/rollback CLI for one test-owned launchd label.

No global install, login item, privileged helper or account change: everything
lives under an explicit private ``--root`` and a ``com.binnacle.r3test.`` label.
A3's launchd lifecycle is injected by composition; without one, apply and
rollback report CapabilityUnavailable rather than shelling out to launchctl.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import stat
import sys
from collections.abc import Sequence
from pathlib import Path

from binnacle.deployment.darwin.plist import (
    DEFAULT_ROLE,
    SERVICE_ROLES,
    validate_test_label,
)
from binnacle.deployment.darwin.provisioner import (
    _LIMITED,
    DarwinProvisioner,
    LaunchdLifecycle,
    ProvisionError,
    ServiceLease,
    ServicePlan,
    UnsafePath,
    ensure_private_subdir,
    sha256_hex,
)


def _lease(root: Path, label: str) -> ServiceLease:
    st = os.lstat(root)
    return ServiceLease(os.getuid(), label, "r3test", st.st_dev, st.st_ino)


def _plan_file(root: Path, label: str) -> Path:
    return root / "plans" / f"{label}.json"


def _write_private(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp{os.getpid()}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _save_plan(root: Path, plan: ServicePlan) -> None:
    plans = ensure_private_subdir(root, "plans", os.getuid())
    doc = {
        "label": plan.lease.label,
        "plist_b64": base64.b64encode(plan.plist_bytes).decode(),
        "plist_sha256": sha256_hex(plan.plist_bytes),
        "expected_previous_sha256": plan.expected_previous_sha256,
    }
    _write_private(plans / f"{plan.lease.label}.json", json.dumps(doc, sort_keys=True))


def _load_plan(root: Path, label: str) -> ServicePlan:
    ensure_private_subdir(root, "plans", os.getuid())
    path = _plan_file(root, label)
    st = os.lstat(path)
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise UnsafePath("plan_file_not_private", _LIMITED)
    doc = json.loads(path.read_text())
    data = base64.b64decode(doc["plist_b64"])
    if doc.get("label") != label or doc.get("plist_sha256") != sha256_hex(data):
        raise UnsafePath("plan_file_tampered", _LIMITED)
    # The plist path is derived, never taken from the (editable) plan file.
    return ServicePlan(
        _lease(root, label),
        data,
        root / f"{label}.plist",
        doc["expected_previous_sha256"],
    )


def _emit(root: Path, label: str, doc: dict[str, object]) -> None:
    receipts = ensure_private_subdir(root, "receipts", os.getuid())
    text = json.dumps(doc, sort_keys=True, indent=1)
    _write_private(receipts / f"{label}.{doc['action']}.json", text)
    print(text)


def main(
    argv: Sequence[str] | None = None, *, lifecycle: LaunchdLifecycle | None = None
) -> int:
    ap = argparse.ArgumentParser(prog="binnacle-darwin-test-setup")
    ap.add_argument("command", choices=("plan", "apply", "rollback"))
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--workdir", type=Path)
    ap.add_argument("--role", choices=SERVICE_ROLES, default=DEFAULT_ROLE)
    ap.add_argument("--exec", dest="exec_argv", nargs="+", default=None)
    args = ap.parse_args(argv)
    root: Path = args.root
    try:
        validate_test_label(args.label)
        if not root.is_absolute():
            raise ValueError("root_not_absolute")
        prov = DarwinProvisioner(
            root,
            uid=os.getuid(),
            lifecycle=lifecycle,
        )
        if args.command == "plan":
            if not args.exec_argv:
                raise ValueError("exec_required")
            plan = prov.plan(
                _lease(root, args.label),
                argv=args.exec_argv,
                environment={},
                workdir=args.workdir or root,
                role=args.role,
            )
            _save_plan(root, plan)
            receipt: dict[str, object] = {
                "action": "plan",
                "label": args.label,
                "plist_sha256": sha256_hex(plan.plist_bytes),
                "expected_previous_sha256": plan.expected_previous_sha256,
            }
        else:
            plan = _load_plan(root, args.label)
            r = (prov.apply if args.command == "apply" else prov.rollback)(plan)
            receipt = {
                "action": r.action,
                "label": args.label,
                "capability": r.capability.state,
                "scope": r.capability.scope,
                "absent": r.absent,
                "full_parity": False,
            }
            if args.command == "rollback" and not r.absent:
                _emit(root, args.label, {**receipt, "error": "teardown_unverified"})
                return 3
        _emit(root, args.label, receipt)
        return 0
    except ProvisionError as exc:
        print(json.dumps({"error": exc.code}), file=sys.stderr)
        return 2
    except (ValueError, OSError) as exc:
        print(
            json.dumps({"error": type(exc).__name__, "detail": str(exc)}),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
