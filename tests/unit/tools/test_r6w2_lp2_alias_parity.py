"""list_files alias prefixes: Linux and Darwin choose the prefix once (r6 W2 LP-a2).

R-LP-F1/F2: the Linux path chooses the first of (root, *live aliases) that
accepts absolute link text, lexically, and walks the link once, as the
Darwin adapter does; it never retries the walk with another prefix.
R-LP-F3: an alias only applies to the root it was configured for, and a
relative configured root string is never an alias. Each case runs the
Darwin adapter and the Linux path on the same tree.
"""

from __future__ import annotations

import shutil
import statistics
import tempfile
import time
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest

from binnacle.config import RootsSettings
from binnacle.features.files import paths
from binnacle.features.files.tools import list_files as lf
from binnacle.platform.contracts.capability_contracts import (
    Capability,
    CapabilityState,
)
from binnacle.platform.darwin.file_access import DarwinFileAccess


def access_for(roots: RootsSettings) -> paths.FileToolAccess:
    return paths.FileToolAccess(
        roots=roots,
        files=DarwinFileAccess(),
        search=None,
        generation="r6w2-lp2",
        capability=Capability(CapabilityState.LIMITED, "test_only", "opened-object"),
    )


def link(at: Path, text: Path | str, is_dir: bool = False) -> None:
    at.symlink_to(text, target_is_directory=is_dir)


def both(roots: RootsSettings, path: Path) -> dict[str, dict]:
    """The listing of path through the Darwin adapter and the Linux path."""
    out = {}
    with closing(access_for(roots)) as access:
        for impl, files in (("darwin", access), ("linux", None)):
            payload = lf.list_files_impl(
                str(path), None, 1000, False, roots=roots, file_access=files
            ).structured_content
            assert payload is not None
            out[impl] = {
                Path(e["path"]).name: (e["type"], e.get("bytes"))
                for e in payload["entries"]
            }
    return out


@pytest.fixture
def fx() -> Iterator[Path]:
    # Non-secret fixtures under /tmp/r6w2-lp2-* (task card write list).
    base = Path(tempfile.mkdtemp(prefix="r6w2-lp2-", dir="/tmp"))
    try:
        yield base.resolve()
    finally:
        shutil.rmtree(base)


def test_a10_alias_inside_the_root_does_not_reopen_a_failed_walk(fx):
    """A10: real/self -> real (absolute text) is also configured as a root.

    The canonical prefix accepts FX/real/self/f.txt, and its walk passes the
    absolute-text symlink 'self', so the link is omitted. The alias prefix
    is never tried for a second walk.
    """
    real = fx / "real"
    real.mkdir()
    (real / "f.txt").write_text("ff")
    link(real / "self", real, True)
    link(real / "through_self", real / "self" / "f.txt")
    roots = RootsSettings(default_root=real, extra_roots=(real / "self",))
    assert roots.canonical_allowed == (real, real)
    listed = both(roots, real)
    expected = {"f.txt": ("file", 2), "self": ("dir", None)}
    assert listed["linux"] == listed["darwin"] == expected


def test_alias_retargeted_to_another_root_is_not_that_roots_alias(fx):
    """F3a: A names R1 at the snapshot; retargeted to R2, it is not R2's alias."""
    r1, r2 = fx / "r1", fx / "r2"
    for d in (r1, r2):
        d.mkdir()
    (r2 / "f.txt").write_text("fff")
    alias = fx / "a"
    link(alias, r1, True)
    roots = RootsSettings(default_root=alias, extra_roots=(r2,))
    assert roots.canonical_allowed == (r1, r2)  # The snapshot binds A to R1.
    alias.unlink()
    link(alias, r2, True)  # Retargeted before the grants and the call.
    link(r2 / "via_a", alias / "f.txt")
    link(r2 / "via_r2", r2 / "f.txt")
    listed = both(roots, r2)
    expected = {"f.txt": ("file", 3), "via_r2": ("file", 3)}
    assert listed["linux"] == listed["darwin"] == expected


def test_relative_configured_root_string_is_never_an_alias(fx, monkeypatch):
    """F3b: 'a' resolves from the cwd to the root but is not absolute."""
    real = fx / "real"
    real.mkdir()
    (real / "f.txt").write_text("ff")
    link(fx / "a", real, True)
    monkeypatch.chdir(fx)
    roots = RootsSettings(default_root=real, extra_roots=(Path("a"),))
    assert roots.canonical_allowed == (real, real)
    link(real / "via_rel", "/a/f.txt")  # Text under the relative string.
    link(real / "via_canon", real / "f.txt")
    listed = both(roots, real)
    expected = {"f.txt": ("file", 2), "via_canon": ("file", 2)}
    assert listed["linux"] == listed["darwin"] == expected
    with closing(access_for(roots)) as access:
        assert access.grants[real].aliases == ()


def test_alias_with_dotdot_never_matches(fx):
    """F4: a configured alias with '..' is filtered on both systems."""
    real, d = fx / "real", fx / "d"
    for p in (real, d):
        p.mkdir()
    (real / "f.txt").write_text("ff")
    dotdot = Path(f"{d}/../real")
    roots = RootsSettings(default_root=real, extra_roots=(dotdot,))
    link(real / "via_dotdot", f"{dotdot}/f.txt")
    listed = both(roots, real)
    assert listed["linux"] == listed["darwin"] == {"f.txt": ("file", 2)}
    assert lf._names(dotdot, real.stat()) is False
    assert lf._names(real, real.stat()) is True


def _median(roots: RootsSettings, real: Path) -> float:
    times = []
    for _ in range(5):
        start = time.perf_counter()
        lf.list_files_impl(str(real), None, 1000, False, roots=roots)
        times.append(time.perf_counter() - start)
    return statistics.median(times)


def test_many_aliases_do_not_multiply_the_link_walks(fx):
    """F2: 300 dangling + 300 absolute links, 200 aliases: within 2x (was 31x)."""
    real = fx / "real"
    real.mkdir()
    (real / "f.txt").write_text("ff")
    for i in range(300):
        link(real / f"dang{i}", f"missing{i}")
        link(real / f"abs{i}", real / "f.txt")
    aliases = []
    for i in range(200):
        alias = fx / f"al{i}"
        link(alias, real, True)
        aliases.append(alias)
    plain = RootsSettings(default_root=real, extra_roots=())
    many = RootsSettings(default_root=real, extra_roots=tuple(aliases))
    # One median each; the faster of three rounds absorbs host noise.
    ratio = min(_median(many, real) / _median(plain, real) for _ in range(3))
    assert ratio < 2.0, ratio
