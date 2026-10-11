"""Test-owned Darwin install transaction and package smoke (A6)."""

from __future__ import annotations

import base64
import dataclasses
import json
import os
import platform
import plistlib
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from binnacle.deployment.darwin import setup
from binnacle.deployment.darwin.plist import render_plist, validate_test_label
from binnacle.deployment.darwin.provisioner import (
    ApplyUnknown,
    CapabilityUnavailable,
    DarwinProvisioner,
    GenerationMismatch,
    ServiceLease,
    UnsafePath,
    sha256_hex,
)

LABEL = "com.binnacle.r3test.pkg"
REPO = Path(__file__).resolve().parents[3]


class FakeLifecycle:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.loaded = False
        self.stuck = False

    def bootstrap(self, label: str, plist_path: Path) -> None:
        self.calls.append("bootstrap")
        self.loaded = True

    def bootout(self, label: str) -> None:
        self.calls.append("bootout")
        self.loaded = self.stuck

    def is_absent(self, label: str) -> bool:
        return not self.loaded


@pytest.fixture
def root(tmp_path: Path) -> Path:
    r = tmp_path / "root"
    r.mkdir(mode=0o700)
    return r


def _plan(root: Path, lc: FakeLifecycle | None = None):
    prov = DarwinProvisioner(root, uid=os.getuid(), lifecycle=lc)
    st = os.lstat(root)
    lease = ServiceLease(os.getuid(), LABEL, "g1", st.st_dev, st.st_ino)
    plan = prov.plan(
        lease, argv=["/usr/bin/true"], environment={"A": "1"}, workdir=root
    )
    return prov, plan


def test_plist_is_deterministic_and_inert(root: Path) -> None:

    def render() -> bytes:
        return render_plist(
            LABEL,
            argv=["/usr/bin/true"],
            environment={"B": "2", "A": "1"},
            workdir=root,
            runtime_dir=root,
        )

    a = render()
    assert a == render()
    assert b"<key>Sockets</key>" not in a
    assert b"RunAtLoad</key>\n\t<false/>" in a


@pytest.mark.parametrize(
    "label", ["com.apple.x", "com.binnacle.r3test.", "com.binnacle.r3test.a/b", ""]
)
def test_non_test_labels_refused(label: str) -> None:
    with pytest.raises(ValueError):
        validate_test_label(label)


def test_apply_rollback_restores_exact_prior_bytes(root: Path) -> None:
    prior = root / f"{LABEL}.plist"
    prior.write_bytes(b"old")
    lc = FakeLifecycle()
    prov, plan = _plan(root, lc)
    assert plan.expected_previous_sha256 == sha256_hex(b"old")
    assert prov.apply(plan).capability.state == "LIMITED"
    assert prior.read_bytes() == plan.plist_bytes
    assert prov.rollback(plan).absent is True
    assert prior.read_bytes() == b"old"


def test_rollback_without_prior_removes_plist(root: Path) -> None:
    lc = FakeLifecycle()
    prov, plan = _plan(root, lc)
    prov.apply(plan)
    assert prov.rollback(plan).absent
    assert not plan.plist_path.exists()


def test_incomplete_rollback_is_not_success_and_keeps_ownership(root: Path) -> None:
    lc = FakeLifecycle()
    prov, plan = _plan(root, lc)
    prov.apply(plan)
    lc.stuck = True
    receipt = prov.rollback(plan)
    assert receipt.absent is False
    assert plan.plist_path.read_bytes() == plan.plist_bytes
    lc.stuck = False
    assert prov.rollback(plan).absent


def test_foreign_plist_preserved_without_bootout(root: Path) -> None:
    lc = FakeLifecycle()
    prov, plan = _plan(root, lc)
    prov.apply(plan)
    plan.plist_path.write_bytes(b"foreign")
    with pytest.raises(GenerationMismatch):
        prov.rollback(plan)
    assert plan.plist_path.read_bytes() == b"foreign"
    assert lc.calls == ["bootstrap"]


def test_apply_rejects_stale_previous_digest(root: Path) -> None:
    lc = FakeLifecycle()
    prov, plan = _plan(root, lc)
    plan.plist_path.write_bytes(b"raced")
    with pytest.raises(GenerationMismatch):
        prov.apply(plan)
    assert plan.plist_path.read_bytes() == b"raced"


def test_bootstrap_failure_restores_prior(root: Path) -> None:
    class Boom(FakeLifecycle):
        def bootstrap(self, label: str, plist_path: Path) -> None:
            raise RuntimeError("boom")

    prov, plan = _plan(root, Boom())
    with pytest.raises(RuntimeError):
        prov.apply(plan)
    assert not plan.plist_path.exists()


class LoadThenRaise(FakeLifecycle):
    def bootstrap(self, label: str, plist_path: Path) -> None:
        super().bootstrap(label, plist_path)
        raise RuntimeError("readiness_failed_after_load")


def test_partial_apply_boots_out_then_restores(root: Path) -> None:
    lc = LoadThenRaise()
    prov, plan = _plan(root, lc)
    with pytest.raises(RuntimeError):
        prov.apply(plan)
    assert lc.is_absent(LABEL)
    assert lc.calls == ["bootstrap", "bootout"]
    assert not plan.plist_path.exists()


def test_partial_apply_with_stuck_label_keeps_plist_and_reports_unknown(
    root: Path,
) -> None:
    lc = LoadThenRaise()
    lc.stuck = True
    prov, plan = _plan(root, lc)
    with pytest.raises(ApplyUnknown) as info:
        prov.apply(plan)
    assert info.value.capability.state == "UNKNOWN"
    assert plan.plist_path.read_bytes() == plan.plist_bytes
    lc.stuck = False
    assert prov.rollback(plan).absent
    assert not plan.plist_path.exists()


def test_apply_refuses_edited_plan_before_bootstrap(root: Path) -> None:
    lc = FakeLifecycle()
    prov, plan = _plan(root, lc)
    body = plistlib.loads(plan.plist_bytes)
    for key, value in (
        ("Label", "com.apple.evil"),
        ("RunAtLoad", True),
        ("KeepAlive", True),
        ("ProgramArguments", ["rel"]),
    ):
        bad = dict(body, **{key: value})
        edited = dataclasses.replace(plan, plist_bytes=plistlib.dumps(bad))
        with pytest.raises(UnsafePath):
            prov.apply(edited)
    assert lc.calls == []
    assert not plan.plist_path.exists()


@pytest.mark.parametrize("sub", ["backups"])
def test_symlinked_subdir_refused(root: Path, tmp_path: Path, sub: str) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, root / sub)
    (root / f"{LABEL}.plist").write_bytes(b"old")
    lc = FakeLifecycle()
    prov, plan = _plan(root, lc)
    with pytest.raises(UnsafePath):
        prov.apply(plan)
    assert list(outside.iterdir()) == []
    assert lc.calls == []


def test_open_mode_subdir_refused(root: Path) -> None:
    (root / "backups").mkdir(mode=0o755)
    (root / "backups").chmod(0o755)
    (root / f"{LABEL}.plist").write_bytes(b"old")
    prov, plan = _plan(root, FakeLifecycle())
    with pytest.raises(UnsafePath):
        prov.apply(plan)


def test_repeated_rollback_with_prior_is_idempotent(root: Path) -> None:
    (root / f"{LABEL}.plist").write_bytes(b"prior")
    lc = FakeLifecycle()
    prov, plan = _plan(root, lc)
    prov.apply(plan)
    assert prov.rollback(plan).absent
    assert prov.rollback(plan).absent
    assert plan.plist_path.read_bytes() == b"prior"


def test_plist_matches_a3_accepted_format(root: Path) -> None:
    _, plan = _plan(root, FakeLifecycle())
    assert plan.plist_path.parent == root
    value = plistlib.loads(plan.plist_bytes)
    env = value["EnvironmentVariables"]
    assert env["BINNACLE_SERVICE_ROLE"] in ("frontend", "probe", "manager")
    assert env["BINNACLE_RUNTIME_DIR"] == str(root)
    assert value["LimitLoadToSessionType"] == "Background"
    assert value["KeepAlive"] is False and value["RunAtLoad"] is False
    for key in ("Program", "UserName", "GroupName", "Sockets", "MachServices"):
        assert key not in value


def test_plist_has_no_raw_log_paths(root: Path) -> None:
    _, plan = _plan(root, FakeLifecycle())
    value = plistlib.loads(plan.plist_bytes)
    assert "StandardOutPath" not in value and "StandardErrorPath" not in value
    assert not (root / "logs").exists()


def test_applied_plist_is_private_file(root: Path) -> None:
    prov, plan = _plan(root, FakeLifecycle())
    prov.apply(plan)
    assert stat.S_IMODE(os.lstat(plan.plist_path).st_mode) == 0o600


def test_cli_refuses_tampered_plan_file(root: Path) -> None:
    lc = FakeLifecycle()
    base = ["--root", str(root), "--label", LABEL]
    assert setup.main(["plan", *base, "--exec", "/usr/bin/true"], lifecycle=lc) == 0
    pf = root / "plans" / f"{LABEL}.json"
    assert stat.S_IMODE(pf.stat().st_mode) == 0o600
    doc = json.loads(pf.read_text())
    body = plistlib.loads(base64.b64decode(doc["plist_b64"]))
    body.update(Label="com.apple.evil", RunAtLoad=True, KeepAlive=True)
    doc["plist_b64"] = base64.b64encode(plistlib.dumps(body)).decode()
    pf.write_text(json.dumps(doc))
    assert setup.main(["apply", *base], lifecycle=lc) == 2
    # Attacker also fixes the digest: semantic validation still refuses.
    doc["plist_sha256"] = sha256_hex(base64.b64decode(doc["plist_b64"]))
    pf.write_text(json.dumps(doc))
    assert setup.main(["apply", *base], lifecycle=lc) == 2
    assert lc.calls == []
    assert not (root / f"{LABEL}.plist").exists()


def test_without_lifecycle_apply_is_unavailable(root: Path) -> None:
    prov, plan = _plan(root, None)
    with pytest.raises(CapabilityUnavailable):
        prov.apply(plan)
    assert not plan.plist_path.exists()


def test_group_readable_root_refused(tmp_path: Path) -> None:
    r = tmp_path / "open"
    r.mkdir()
    r.chmod(0o755)
    with pytest.raises(UnsafePath):
        _plan(r, FakeLifecycle())


def test_root_identity_mismatch_refused(root: Path) -> None:
    prov, plan = _plan(root, FakeLifecycle())
    other = root.parent / "other"
    other.mkdir(mode=0o700)
    root.rename(root.parent / "moved")
    other.rename(root)
    with pytest.raises(GenerationMismatch):
        prov.apply(plan)


def test_cli_roundtrip_and_global_label_refused(root: Path) -> None:
    lc = FakeLifecycle()
    base = ["--root", str(root), "--label", LABEL]
    assert setup.main(["plan", *base, "--exec", "/usr/bin/true"], lifecycle=lc) == 0
    assert setup.main(["apply", *base], lifecycle=lc) == 0
    assert setup.main(["rollback", *base], lifecycle=lc) == 0
    assert (root / "receipts" / f"{LABEL}.rollback.json").exists()
    assert (
        setup.main(
            ["plan", "--root", str(root), "--label", "com.apple.x", "--exec", "/bin/x"],
            lifecycle=lc,
        )
        == 1
    )


def test_darwin_modules_import_without_linux_services() -> None:
    code = (
        "import sys, binnacle.deployment.darwin.setup;"
        "bad=[m for m in sys.modules if m.startswith('binnacle.platform.linux') or 'systemd' in m];"
        "sys.exit(1 if bad else 0)"
    )
    r = subprocess.run(
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr


@pytest.mark.skipif(
    not (sys.platform == "darwin" and platform.machine() == "arm64"),
    reason="arm64 macOS wheel smoke is Darwin-only; Linux covers module import above",
)
def test_arm64_locked_wheel_install_smoke(tmp_path: Path) -> None:
    receipt = tmp_path / "r.json"
    r = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "macos_package_smoke.py"),
            "--repo",
            str(REPO),
            "--receipt",
            str(receipt),
        ],
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    assert r.returncode == 0, r.stdout + r.stderr
