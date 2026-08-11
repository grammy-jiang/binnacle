"""The concrete authentication adapter is gated on live feasibility evidence."""

from __future__ import annotations

from pathlib import Path


def test_no_concrete_auth_profile_is_implemented_speculatively(repo_root: Path) -> None:
    adapters = repo_root / "src/binnacle/adapters"

    assert not (adapters / "auth_gateway.py").exists()
    assert not (adapters / "auth_oauth.py").exists()
