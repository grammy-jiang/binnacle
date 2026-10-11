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
    pinned_root,
    pinned_subdir,
    read_regular_at,
    sha256_hex,
    write_atomic_at,
)


def _lease(root: Path, label: str) -> ServiceLease:
    with pinned_root(root, os.getuid()) as fd:
        st = os.fstat(fd)
    return ServiceLease(os.getuid(), label, "r3test", st.st_dev, st.st_ino)


def _save_plan(root: Path, plan: ServicePlan) -> None:
    doc = {
        "label": plan.lease.label,
        "plist_b64": base64.b64encode(plan.plist_bytes).decode(),
        "plist_sha256": sha256_hex(plan.plist_bytes),
        "expected_previous_sha256": plan.expected_previous_sha256,
    }
    uid = os.getuid()
    with pinned_root(root, uid) as root_fd, pinned_subdir(root_fd, "plans", uid) as fd:
        write_atomic_at(
            fd, f"{plan.lease.label}.json", json.dumps(doc, sort_keys=True).encode()
        )


def _load_plan(root: Path, label: str) -> ServicePlan:
    uid = os.getuid()
    with pinned_root(root, uid) as root_fd:
        st = os.fstat(root_fd)
        with pinned_subdir(root_fd, "plans", uid) as fd:
            raw = read_regular_at(fd, f"{label}.json", private_uid=uid)
    if raw is None:
        raise FileNotFoundError("plan_file_missing")
    doc = json.loads(raw)
    data = base64.b64decode(doc["plist_b64"])
    if doc.get("label") != label or doc.get("plist_sha256") != sha256_hex(data):
        raise UnsafePath("plan_file_tampered", _LIMITED)
    # The plist path is derived, never taken from the (editable) plan file.
    return ServicePlan(
        ServiceLease(uid, label, "r3test", st.st_dev, st.st_ino),
        data,
        root / f"{label}.plist",
        doc["expected_previous_sha256"],
    )


def _emit(root: Path, label: str, doc: dict[str, object]) -> None:
    text = json.dumps(doc, sort_keys=True, indent=1)
    uid = os.getuid()
    with (
        pinned_root(root, uid) as root_fd,
        pinned_subdir(root_fd, "receipts", uid) as fd,
    ):
        write_atomic_at(fd, f"{label}.{doc['action']}.json", text.encode())
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
