"""E1-a6 (SD-90, Ruling A): the server's REQUIRED set is a frozen literal.

``binnacle.startup_server_modules.SERVER_MODULES`` is generated once by
``scripts/gen_startup_server_modules.py``. A drift test holds it equal to the
walk of the binnacle source tree minus the exclusions pinned in
``startup_imports`` and tells the developer how to regenerate it. The RUNTIME
imports only the literal: it never walks the installed package directory, so a
stray ``.py`` there is never imported. Identical on both OSes (the literal and
the walk cover both OSes from either host). Test homes live under
~/.local/state/bt/e1a6 (0700, exact-path teardown).
"""

from __future__ import annotations

import os
import pkgutil
import shutil
import subprocess
import sys
import textwrap
import uuid
from contextlib import suppress
from pathlib import Path

import pytest

from binnacle import startup_imports, startup_server_modules
from scripts import gen_startup_server_modules as gen

REPO = Path(__file__).resolve().parents[3]
TEST_ROOT = Path.home() / ".local" / "state" / "bt" / "e1a6"
SYSTEMS = ("Linux", "Darwin")


@pytest.fixture
def home():
    TEST_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(TEST_ROOT, 0o700)
    path = TEST_ROOT / f"ss-{uuid.uuid4().hex[:12]}"
    path.mkdir(mode=0o700)
    yield path
    shutil.rmtree(path)  # exact path this fixture created
    with suppress(OSError):  # only when no other test home remains
        TEST_ROOT.rmdir()


def _drift(system: str, literal, walked) -> str:
    return (
        f"SERVER_MODULES[{system!r}] drifted from the source tree minus the pinned "
        f"exclusions (only in the literal: {sorted(set(literal) - set(walked))}; "
        f"only in the tree: {sorted(set(walked) - set(literal))}); "
        f"regenerate with: {gen.COMMAND}"
    )


@pytest.mark.parametrize("system", SYSTEMS)
def test_the_literal_equals_the_walk_minus_the_pinned_exclusions(system):
    literal = startup_imports.runtime_module_names(system)
    walked = gen.walk_server_modules(system)
    assert literal == walked, _drift(system, literal, walked)
    assert literal == startup_server_modules.SERVER_MODULES[system]
    assert list(literal) == sorted(set(literal))


def test_the_generated_file_is_byte_identical_to_the_generator_output():
    path = Path(startup_server_modules.__file__)
    assert path.read_text(encoding="utf-8") == gen.render(), (
        f"{path.name} differs from the generator output; regenerate with: {gen.COMMAND}"
    )
    assert gen.COMMAND.endswith("gen_startup_server_modules.py --write")


def test_the_generator_check_and_write_modes(tmp_path, monkeypatch, capsys):
    target = tmp_path / "startup_server_modules.py"
    monkeypatch.setattr(gen, "TARGET", target)
    target.write_text("SERVER_MODULES = {}\n", encoding="utf-8")  # a stale literal
    assert gen.main(["--check"]) == 1
    assert f"regenerate with: {gen.COMMAND}" in capsys.readouterr().out
    assert gen.main(["--write"]) == 0
    assert target.read_text(encoding="utf-8") == gen.render()
    assert gen.main(["--check"]) == 0 and capsys.readouterr().out == ""
    before = target.stat().st_mtime_ns
    assert gen.main(["--write"]) == 0  # idempotent: nothing to rewrite
    assert target.stat().st_mtime_ns == before
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("system", SYSTEMS)
def test_a_module_missing_from_the_literal_fails_the_drift_check(system):
    # Mutant: a runtime module added to the tree but not to the literal (or the
    # reverse). The same comparison the drift test makes must see it.
    literal = startup_imports.runtime_module_names(system)
    walked = gen.walk_server_modules(system)
    for mutated in (literal[1:], (*literal, "binnacle.zz_removed")):
        assert mutated != walked
        assert gen.COMMAND in _drift(system, mutated, walked)


@pytest.mark.parametrize("system", SYSTEMS)
def test_the_runtime_imports_exactly_the_literal(system, monkeypatch):
    seen = []

    def record(name):
        seen.append(name)

    def refuse(*args, **kwargs):
        raise AssertionError("the runtime walked the package directory")

    for owner, attr in (
        (pkgutil, "iter_modules"),
        (pkgutil, "walk_packages"),
        (os, "scandir"),
        (os, "listdir"),
        (os, "walk"),
        (Path, "iterdir"),
        (Path, "glob"),
        (Path, "rglob"),
    ):
        monkeypatch.setattr(owner, attr, refuse)
    monkeypatch.setattr(startup_imports.importlib, "import_module", record)
    assert startup_imports.import_runtime_modules(system) == ()
    assert seen == list(startup_server_modules.SERVER_MODULES[system])


STRAY = textwrap.dedent(
    """
    import json, pkgutil, sys
    from pathlib import Path
    stray_root, marker = Path(sys.argv[1]), Path(sys.argv[2])
    import binnacle, binnacle.features.files as files
    from binnacle.startup_imports import import_runtime_modules
    for package, leaf in ((binnacle, "zz_e1g_stray"), (files, "zz_e1g_stray_files")):
        (stray_root / package.__name__).mkdir(parents=True, exist_ok=True)
        (stray_root / package.__name__ / (leaf + ".py")).write_text(
            f"from pathlib import Path\\nPath({str(marker)!r}).write_text('{leaf}')\\n"
        )
        package.__path__.append(str(stray_root / package.__name__))
    # control: a walk of the installed package directories DOES find the strays
    found = {m.name for p in (binnacle, files)
             for m in pkgutil.iter_modules(p.__path__, p.__name__ + ".")}
    assert {"binnacle.zz_e1g_stray", "binnacle.features.files.zz_e1g_stray_files"} <= found
    import_runtime_modules()
    loaded = sorted(m for m in sys.modules if "zz_e1g_stray" in m)
    print(json.dumps({"loaded": loaded, "marker": marker.exists()}))
    """
)


def test_a_stray_file_in_the_package_directory_is_never_imported(home):
    done = subprocess.run(
        [sys.executable, "-c", STRAY, str(home / "stray"), str(home / "marker")],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-3000:]
    assert done.stdout.strip().splitlines()[-1] == '{"loaded": [], "marker": false}'


WALK_IMPORTS_NOTHING = textwrap.dedent(
    """
    import sys
    from scripts import gen_startup_server_modules as gen
    import binnacle.startup_imports  # the walk's own exclusion tuples
    before = {m for m in sys.modules if m.startswith("binnacle")}
    for system in ("Linux", "Darwin"):
        gen.walk_server_modules(system)
    late = sorted({m for m in sys.modules if m.startswith("binnacle")} - before)
    print(late)
    sys.exit(1 if late else 0)
    """
)


def test_the_generator_walk_imports_no_binnacle_module():
    done = subprocess.run(
        [sys.executable, "-c", WALK_IMPORTS_NOTHING],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, (done.stdout, done.stderr[-2000:])


def test_optional_webmin_companion_never_enters_required_core_server_set():
    """E1 eager imports preserve the pre-existing core/companion boundary."""
    for system in SYSTEMS:
        assert (
            "binnacle.observability.linux.webminstats"
            not in startup_imports.runtime_module_names(system)
        )
