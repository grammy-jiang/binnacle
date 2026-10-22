"""Private E02 key validation must not depend on the runner's umask.

The two independent negative controls preserve the actual production
ownership/mode security gate and the separate partial-key recovery gate.
"""

from __future__ import annotations

import stat

import pytest


def test_partial_private_key_requires_explicit_recovery(tmp_path):
    from scripts import lsp_e02_private as private

    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    key = root / "e02-local-key.bin"
    key.write_bytes(b"partial")
    # A Runner may use umask 0022, yielding 0644 from write_bytes. Ensure
    # this test isolates the *incomplete key* rule rather than the independent
    # ownership/mode denial rule, which is tested immediately below.
    key.chmod(0o600)
    assert stat.S_IMODE(key.stat().st_mode) == 0o600
    with pytest.raises(ValueError, match="manual recovery"):
        private.write_document(root, "sample", {"cases": []})
    assert not (root / "sample.json").exists()


def test_insecure_private_key_permissions_are_rejected_without_recovery(tmp_path):
    from scripts import lsp_e02_private as private

    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    key = root / "e02-local-key.bin"
    key.write_bytes(b"k" * 32)
    # Deterministic on restrictive and permissive hosts alike. No product
    # permission check is bypassed just to make GitHub CI green.
    key.chmod(0o644)
    assert stat.S_IMODE(key.stat().st_mode) == 0o644
    with pytest.raises(PermissionError, match="ownership/mode invalid"):
        private.write_document(root, "sample", {"cases": []})
    assert not (root / "sample.json").exists()
