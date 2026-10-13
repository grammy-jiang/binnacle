"""RG1: the doctor reports the ripgrep version and WARNs off the pin."""

import stat
from pathlib import Path

from binnacle.diagnostics import doctor_provenance


def _fake_rg(tmp_path: Path, banner: str) -> str:
    path = tmp_path / "rg"
    path.write_text(f"#!/bin/sh\necho '{banner}'\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


def test_pinned_version_is_ok(tmp_path: Path) -> None:
    rg = _fake_rg(tmp_path, f"ripgrep {doctor_provenance.PINNED_RG_VERSION} (rev abc)")
    (check,) = doctor_provenance.check_rg_version(rg)
    assert check.status == "ok"
    assert f"version={doctor_provenance.PINNED_RG_VERSION}" in check.detail


def test_other_version_warns(tmp_path: Path) -> None:
    rg = _fake_rg(tmp_path, "ripgrep 14.1.1")
    (check,) = doctor_provenance.check_rg_version(rg, pinned="15.2.0")
    assert check.status == "warn"
    assert "14.1.1" in check.detail
    assert "15.2.0" in check.detail
    assert "rg_bin" in check.hint


def test_missing_binary_warns() -> None:
    (check,) = doctor_provenance.check_rg_version("/nonexistent/rg-r6w3-rg1")
    assert check.status == "warn"


def test_unparseable_banner_warns(tmp_path: Path) -> None:
    (check,) = doctor_provenance.check_rg_version(_fake_rg(tmp_path, "not ripgrep"))
    assert check.status == "warn"
