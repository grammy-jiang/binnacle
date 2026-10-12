"""macOS: a root configured as /tmp lists /tmp and /private/tmp link text (r6 W2 LP).

The configured string /tmp is the alias of the canonical root /private/tmp
(SD-74, LP ruling). The gate compares text case-sensitively and never
consults the filesystem, so case-variant alias text stays omitted on the
case-insensitive default volume.
"""

from __future__ import annotations

import sys
import tempfile
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

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="/tmp is a symlink to /private/tmp on macOS"
)


@pytest.fixture
def tmp_root():
    with tempfile.TemporaryDirectory(prefix="r6w2-lp-", dir="/tmp") as made:
        name = Path(made).name
        alias, canonical = Path("/tmp"), Path("/tmp").resolve()
        work = canonical / name
        (work / "d").mkdir()
        (work / "f.txt").write_text("ff")
        roots = RootsSettings(default_root=alias, extra_roots=())
        access = paths.FileToolAccess(
            roots=roots,
            files=DarwinFileAccess(),
            search=None,
            generation="r6w2-lp-tmp",
            capability=Capability(
                CapabilityState.LIMITED, "test_only", "opened-object"
            ),
        )
        with closing(access):
            yield {
                "work": work,
                "alias_work": alias / name,
                "roots": roots,
                "access": access,
            }


def typed(env: dict, *, native: bool) -> dict:
    payload = lf.list_files_impl(
        str(env["alias_work"]),
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


@pytest.mark.parametrize("native", [True, False], ids=["darwin", "linux"])
def test_tmp_and_private_tmp_text_both_listed_case_variant_omitted(tmp_root, native):
    work, alias_work = tmp_root["work"], tmp_root["alias_work"]
    assert work.parts[:3] == ("/", "private", "tmp")
    link = Path.symlink_to
    link(work / "via_tmp", alias_work / "f.txt")
    link(work / "via_private", work / "f.txt")
    link(work / "via_tmp_dir", alias_work / "d", True)
    link(work / "case_tmp", f"/TMP/{alias_work.name}/f.txt")
    link(work / "case_private", f"/Private/tmp/{alias_work.name}/f.txt")
    link(work / "tmp_dd", f"{alias_work}/d/../f.txt")
    assert grant_aliases(tmp_root) == ("/tmp",)
    assert typed(tmp_root, native=native) == {
        "d": ("dir", None),
        "f.txt": ("file", 2),
        "via_private": ("file", 2),
        "via_tmp": ("file", 2),
        "via_tmp_dir": ("dir", None),
    }


def grant_aliases(env: dict) -> tuple[str, ...]:
    return env["access"].grants[Path("/tmp")].aliases
