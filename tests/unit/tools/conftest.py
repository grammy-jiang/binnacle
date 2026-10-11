"""Portable temporary roots for the tool-level unit tests.

The tests build their fixtures under ``tmp_path``. On Linux that is under the
default ``/tmp`` root; on macOS it is under ``$TMPDIR`` (``/var/folders/...``)
which is outside the default roots. Add the pytest temporary directory as an
extra root only when it is not already covered, so Linux behaviour is
byte-for-byte unchanged.
"""

from __future__ import annotations

import pytest

from binnacle.config import get_settings


@pytest.fixture(autouse=True)
def _tmp_path_is_an_allowed_root(tmp_path_factory, monkeypatch):
    roots = get_settings().roots
    base = tmp_path_factory.getbasetemp().resolve()
    if not any(base.is_relative_to(root) for root in roots.canonical_allowed):
        monkeypatch.setattr(roots, "extra_roots", (*roots.extra_roots, base))
