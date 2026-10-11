"""Typed permission boundary, injected TCC-like errno plus real mode denials.

An injected EPERM is not a native TCC receipt. No privacy settings are changed.
"""

import errno
import os
from contextlib import closing

import pytest

from binnacle.platform.contracts.capability_contracts import PermissionDenied
from binnacle.platform.contracts.file_access_contracts import ListRequest, SearchRequest
from binnacle.platform.darwin.file_access import DarwinFileAccess
from binnacle.platform.darwin.search_access import DarwinSearchAccess


@pytest.mark.parametrize("error", [errno.EACCES, errno.EPERM])
@pytest.mark.parametrize(
    "operation", ["grant", "read", "write", "list", "hint", "search"]
)
def test_tcc_like_denial_is_typed_without_widening(
    tmp_path, monkeypatch, error, operation
):
    root = tmp_path.resolve()
    (root / "denied").write_bytes(b"secret")
    calls = []
    real_open = os.open
    with closing(DarwinFileAccess()) as files:
        grant = files.grant(root, generation="g")

        def denied_open(path, flags, *args, **kwargs):
            calls.append((path, kwargs.get("dir_fd")))
            raise OSError(error, "secret-bearing native error")

        monkeypatch.setattr(os, "open", denied_open)
        operations = {
            "grant": lambda: files.grant(root, generation="g2"),
            "read": lambda: files.open_read(grant, "denied"),
            "write": lambda: files.write_bytes(grant, "denied", b"bad"),
            "list": lambda: files.list_entries(
                grant, ListRequest(".", None, False, 10, 100, 1)
            ),
            "hint": lambda: files.nearby_hint(grant, "missing", max_entries=10),
            "search": lambda: DarwinSearchAccess(files, rg_bin="rg").search(
                grant, SearchRequest(".", "secret", True, 0, None, 1, 10000, 10)
            ),
        }
        with pytest.raises(PermissionDenied) as failure:
            operations[operation]()
        assert failure.value.code == "permission_denied_tcc_possible"
        assert "secret" not in str(failure.value)
        assert len(calls) == 1  # No retry, privilege request or ancestor fallback.
        if operation != "grant":
            assert calls[0][1] is not None
        assert grant.generation == "g"
        monkeypatch.setattr(os, "open", real_open)
    assert (root / "denied").read_bytes() == b"secret"


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses POSIX mode denials")
def test_native_unreadable_file_and_unauthorized_write(tmp_path):
    root = tmp_path.resolve()
    target = root / "denied"
    target.write_bytes(b"secret")
    with closing(DarwinFileAccess()) as files:
        grant = files.grant(root, generation="g")
        try:
            target.chmod(0)
            with pytest.raises(PermissionDenied):
                files.open_read(grant, "denied")
            with pytest.raises(PermissionDenied):
                files.write_bytes(grant, "denied", b"bad")
            with pytest.raises(PermissionDenied):
                DarwinSearchAccess(files, rg_bin="rg").search(
                    grant, SearchRequest(".", "secret", True, 0, None, 1, 10000, 10)
                )
            target.chmod(0o444)
            with pytest.raises(PermissionDenied):
                files.write_bytes(grant, "denied", b"bad")
            assert target.stat().st_mode & 0o777 == 0o444
            root.chmod(0o555)
            with pytest.raises(PermissionDenied):
                files.write_bytes(grant, "new", b"bad")
            assert not (root / "new").exists()
        finally:
            root.chmod(0o700)
            target.chmod(0o600)
    assert target.read_bytes() == b"secret"
    assert not list(root.glob(".binnacle-write-*"))
