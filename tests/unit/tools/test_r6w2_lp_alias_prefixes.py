"""list_files LIST mode accepts absolute link text through a root alias (r6 W2 LP).

SD-74 and the LP ruling: the lexical gate for absolute in-root link text may
match the canonical root prefix or a configured alias string of that root.
An alias is a configured root string only (never inferred), accepted when its
realpath is the canonical root at grant time, and re-checked per call by one
stat compared with the opened root, so a retargeted alias stops matching.
Every check after the gate is unchanged. Each probe runs the Darwin adapter
and the Linux path on the same tree (both run on every POSIX host).
"""

from __future__ import annotations

import os
import shutil
import tempfile
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

SECRET = "s" * 4321  # A size that appears nowhere else in the fixture.
NATIVE = pytest.mark.parametrize("native", [True, False], ids=["darwin", "linux"])


def access_for(roots: RootsSettings) -> paths.FileToolAccess:
    return paths.FileToolAccess(
        roots=roots,
        files=DarwinFileAccess(),
        search=None,
        generation="r6w2-lp",
        capability=Capability(CapabilityState.LIMITED, "test_only", "opened-object"),
    )


def link(at: Path, text: Path | str, is_dir: bool = False) -> None:
    at.symlink_to(text, target_is_directory=is_dir)


def retarget(alias: Path, target: Path) -> None:
    alias.unlink()
    link(alias, target, True)


@pytest.fixture
def env() -> Iterator[dict]:
    # Non-secret fixtures under /tmp/r6w2-lp-* (task card write list).
    base = Path(tempfile.mkdtemp(prefix="r6w2-lp-", dir="/tmp"))
    try:
        real, real2, out = base / "real", base / "real2", base / "out"
        for d in (real, real / "d", real2, out):
            d.mkdir()
        (real / "f.txt").write_text("ff")
        (real2 / "f.txt").write_text("fff")
        (out / "secret.txt").write_text(SECRET)
        link(real / "escape", "../out", True)
        alias = base / "alias"
        link(alias, real, True)
        roots = RootsSettings(default_root=alias, extra_roots=())
        canonical = roots.canonical_allowed[0]  # Binds the snapshot (grant time).
        assert canonical == real.resolve()
        with closing(access_for(roots)) as access:
            yield {
                "base": base,
                "real": canonical,
                "real2": real2.resolve(),
                "alias": alias,
                "roots": roots,
                "access": access,
            }
    finally:
        shutil.rmtree(base)


def typed(env: dict, *, native: bool, path: Path | None = None) -> dict:
    payload = lf.list_files_impl(
        str(path or env["alias"]),
        None,
        200,
        False,
        roots=env["roots"],
        file_access=env["access"] if native else None,
    ).structured_content
    assert payload is not None
    return {
        Path(e["path"]).name: (e["type"], e.get("bytes")) for e in payload["entries"]
    }


BASE = {"d": ("dir", None), "f.txt": ("file", 2)}


@NATIVE
def test_alias_text_is_listed_beside_canonical_text(env, native):
    real, alias = env["real"], env["alias"]
    link(real / "via_alias", alias / "f.txt")
    link(real / "via_alias_dir", f"{alias}//d/./", True)
    link(real / "via_canon", real / "f.txt")
    link(real / "alias_root", alias, True)
    assert typed(env, native=native) == {
        **BASE,
        "alias_root": ("dir", None),
        "via_alias": ("file", 2),
        "via_alias_dir": ("dir", None),
        "via_canon": ("file", 2),
    }


@NATIVE
def test_retargeted_alias_is_ignored_for_the_call(env, native):
    """M1: the per-call identity re-check; canonical text still works."""
    real, alias = env["real"], env["alias"]
    link(real / "via_alias", alias / "f.txt")
    link(real / "via_canon", real / "f.txt")
    assert typed(env, native=native, path=real)["via_alias"] == ("file", 2)
    retarget(alias, env["real2"])
    assert typed(env, native=native, path=real) == {
        **BASE,
        "via_canon": ("file", 2),
    }
    retarget(alias, real)  # Pointing back makes the alias match again.
    assert typed(env, native=native, path=real)["via_alias"] == ("file", 2)


@NATIVE
def test_alias_text_with_dotdot_or_outside_the_root_is_omitted(env, native):
    """M3: the resolved target must still lie inside the canonical root."""
    real, alias, base = env["real"], env["alias"], env["base"]
    link(real / "dd_in", f"{alias}/d/../f.txt")
    link(real / "dd_out", f"{alias}/../out/secret.txt")
    link(real / "escape_out", alias / "escape" / "secret.txt")
    link(real / "escape_dir", alias / "escape", True)
    link(real / "plain_out", base / "out" / "secret.txt")
    link(real / "dangle", alias / "nope")
    assert typed(env, native=native) == BASE


@NATIVE
def test_inferred_alias_is_not_accepted(env, native):
    """M2: only configured root strings are alias prefixes."""
    real, base = env["real"], env["base"]
    other = base / "other"
    link(other, real, True)  # Same realpath as the root, but not configured.
    link(real / "via_other", other / "f.txt")
    link(real / "via_prefix", f"{env['alias']}x/f.txt")
    assert typed(env, native=native) == BASE


@NATIVE
def test_nested_roots_with_an_alias_outer_root(env, native):
    real, alias = env["real"], env["alias"]
    inner = real / "inner"
    inner.mkdir()
    (inner / "g.txt").write_text("ggg")
    link(inner / "to_outer", alias / "f.txt")
    link(real / "outer_ok", alias / "f.txt")
    roots = RootsSettings(default_root=alias, extra_roots=(inner,))
    with closing(access_for(roots)) as access:
        env = {**env, "roots": roots, "access": access}
        assert typed(env, native=native, path=inner) == {"g.txt": ("file", 3)}
        assert typed(env, native=native)["outer_ok"] == ("file", 2)


def test_grant_keeps_only_configured_aliases_naming_the_root(env):
    real, alias, base = env["real"], env["alias"], env["base"]
    with closing(DarwinFileAccess()) as files:
        kept = files.grant(real, generation="lp", aliases=(alias,))
        assert kept.aliases == (str(alias),)
        refused = files.grant(
            real,
            generation="lp",
            aliases=(
                base / "real2",  # realpath is another directory
                Path(f"{base}/real2/../alias"),  # '..' is never normalized away
                Path("alias"),  # relative
                real,  # the canonical root itself
            ),
        )
        assert refused.aliases == ()


def test_file_tool_access_passes_the_configured_alias_strings(env):
    grant = env["access"].grants[env["alias"]]
    assert grant is env["access"].grants[env["real"]]
    assert grant.aliases == (str(env["alias"]),)


def test_canonical_root_configured_without_alias_has_no_alias(env):
    roots = RootsSettings(default_root=env["real"], extra_roots=())
    with closing(access_for(roots)) as access:
        assert access.grants[env["real"]].aliases == ()


def test_alias_identity_uses_one_stat_per_call(env, monkeypatch):
    """The re-check is a cheap per-call identity compare, not per link."""
    real, alias = env["real"], env["alias"]
    for n in range(5):
        link(real / f"l{n}", alias / "f.txt")
    calls: list[str] = []
    real_stat = os.stat

    def counting(p, *args, **kwargs):
        if str(p) == str(alias) and not kwargs.get("dir_fd"):
            calls.append(str(p))
        return real_stat(p, *args, **kwargs)

    monkeypatch.setattr(os, "stat", counting)
    for native in (True, False):
        calls.clear()
        assert len(typed(env, native=native)) == 7
        assert calls == [str(alias)]
