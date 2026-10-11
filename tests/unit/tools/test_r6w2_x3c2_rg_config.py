"""Linux ripgrep ignores RIPGREP_CONFIG_PATH (r6 W2 X3c-a2).

rg reads extra flags from the file named by RIPGREP_CONFIG_PATH. A config
with --follow, --hidden or --no-ignore would widen what rg walks and opens
below the tools' policy. r6 X3c ran rg with the inherited environment and
without --no-config; the head passes --no-config to every Linux rg call and
an environment without the variable. The results with a hostile config
must equal the results without it, and every built argv and environment
is pinned.
"""

import os
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from binnacle.config import RootsSettings, get_settings
from binnacle.errors import CodedToolError
from binnacle.features.files.tools import list_files as lf
from binnacle.features.search import search_text_collect as stc
from binnacle.features.search import search_text_rg as str_rg
from binnacle.features.search import search_text_stream as sts
from binnacle.features.search.rg_env import CONFIG_ENV, NO_CONFIG, rg_env
from binnacle.features.search.tools import search_text as st

RG = shutil.which("rg") or "rg"
CONFIGS = {
    "follow": "--follow\n",
    "hidden": "--hidden\n",
    "no-ignore": "--no-ignore\n",
    "all": "--follow\n--hidden\n--no-ignore\n",
}


@pytest.fixture
def tree(tmp_path: Path) -> dict:
    """A root with a gitignored file, a hidden file and a link outside."""
    root = tmp_path / "root"
    (root / ".git").mkdir(parents=True)  # rg honors .gitignore in a repo
    (root / "d").mkdir()
    (root / ".gitignore").write_text("ignored.txt\n")
    (root / "a.txt").write_text("needle visible\n")
    (root / "d" / "b.txt").write_text("needle deep\n")
    (root / "ignored.txt").write_text("needle ignored\n")
    (root / ".hidden.txt").write_text("needle hidden\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "o.txt").write_text("needle outside\n")
    (root / "link").symlink_to(outside, target_is_directory=True)
    (root / "alias").symlink_to(root / "d", target_is_directory=True)
    roots = RootsSettings(allowed=[str(root)])
    return {"root": root, "roots": roots, "tmp": tmp_path}


def search(tree: dict, execution: str, **kw: Any) -> dict:
    settings = get_settings().search_text.model_copy(
        update={"exact_execution": execution}
    )
    args: dict[str, Any] = {
        "glob": None,
        "fixed_strings": False,
        "context_lines": None,
        "names_only": False,
        "max_results": 100,
    }
    args.update(kw)
    result = st.search_text_impl(
        "needle",
        str(tree["root"]),
        **args,
        roots=tree["roots"],
        settings=settings,
        rg_bin=RG,
    )
    assert result.structured_content is not None
    return result.structured_content


def glob(tree: dict, include_hidden: bool = False) -> dict:
    result = lf.list_files_impl(
        str(tree["root"]),
        "*.txt",
        200,
        include_hidden,
        roots=tree["roots"],
        rg_bin=RG,
    )
    assert result.structured_content is not None
    return result.structured_content


def use_config(tree: dict, monkeypatch, name: str) -> None:
    config = tree["tmp"] / f"rgrc-{name}"
    config.write_text(CONFIGS[name])
    monkeypatch.setenv(CONFIG_ENV, str(config))


def unordered(result: dict) -> tuple[dict, Counter]:
    """The result without entry order: (other fields, entry multiset)."""
    rest = {k: v for k, v in result.items() if k != "entries"}
    entries = Counter(tuple(sorted(e.items())) for e in result["entries"])
    return rest, entries


def test_the_config_widens_a_plain_rg_run(tree, monkeypatch):
    """Precondition: the hostile config does change a config-reading rg."""
    use_config(tree, monkeypatch, "all")
    out = subprocess.run(
        [RG, "--files"],
        cwd=tree["root"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.splitlines()
    assert {"ignored.txt", ".hidden.txt", "link/o.txt"} <= set(out)


@pytest.mark.parametrize("name", sorted(CONFIGS))
@pytest.mark.parametrize("execution", ["materialized", "streaming"])
@pytest.mark.parametrize("names_only", [False, True])
def test_search_text_ignores_the_config(tree, monkeypatch, name, execution, names_only):
    monkeypatch.delenv(CONFIG_ENV, raising=False)
    before = search(tree, execution, names_only=names_only)
    use_config(tree, monkeypatch, name)
    after = search(tree, execution, names_only=names_only)
    # rg walks with parallel workers, so the entry order differs between
    # runs; compare the entries as a multiset and every other field exactly.
    assert unordered(after) == unordered(before)
    assert "needle ignored" not in repr(after)
    assert "needle hidden" not in repr(after)
    assert "needle outside" not in repr(after)
    root = tree["root"]
    files = {Path(e["file"]) for e in after["entries"]}
    # --follow: nothing reached through a symlink, inside or outside the root.
    assert root / "link" / "o.txt" not in files
    assert root / "alias" / "b.txt" not in files
    # --hidden / --no-ignore: the hidden and the gitignored file stay out.
    assert root / "ignored.txt" not in files
    assert root / ".hidden.txt" not in files
    assert files == {root / "a.txt", root / "d" / "b.txt"}


@pytest.mark.parametrize("name", sorted(CONFIGS))
@pytest.mark.parametrize("include_hidden", [False, True])
def test_list_files_glob_ignores_the_config(tree, monkeypatch, name, include_hidden):
    monkeypatch.delenv(CONFIG_ENV, raising=False)
    before = glob(tree, include_hidden)
    use_config(tree, monkeypatch, name)
    after = glob(tree, include_hidden)
    assert after == before
    paths = {Path(e["path"]).name for e in after["entries"]}
    assert "ignored.txt" not in paths
    assert "o.txt" not in paths


@pytest.mark.parametrize("name", sorted(CONFIGS))
def test_the_stream_runner_ignores_the_config(tree, monkeypatch, name):
    def run() -> list[str]:
        """Match and context events only (end/summary carry timings), in a
        canonical order (rg emits files from parallel workers)."""
        stream = sts.RgJsonStream(
            tree["root"], "needle", False, 0, rg_bin=RG, timeout_s=30
        )
        with sts.managed_rg_stream(stream):
            events = list(stream)
        kinds = ("match", "context")
        return sorted(repr(e) for e in events if e.get("type") in kinds)

    monkeypatch.delenv(CONFIG_ENV, raising=False)
    before = run()
    use_config(tree, monkeypatch, name)
    after = run()
    assert after == before
    assert len(before) == 2


# --- argv and environment pins -------------------------------------------


class Captured:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict | None]] = []


@pytest.fixture
def hostile_env(tmp_path, monkeypatch) -> Path:
    config = tmp_path / "rgrc"
    config.write_text("--follow\n")
    monkeypatch.setenv(CONFIG_ENV, str(config))
    monkeypatch.setenv("BINNACLE_X3C2_KEEP", "kept")
    return config


def assert_scrubbed(argv: list[str], env: dict | None) -> None:
    assert argv[1] == NO_CONFIG
    assert env is not None
    assert CONFIG_ENV not in env
    assert env.get("PATH") == os.environ.get("PATH")
    assert env.get("BINNACLE_X3C2_KEEP") == "kept"


def test_rg_env_drops_only_the_config_variable(hostile_env):
    env = rg_env()
    assert CONFIG_ENV not in env
    expected = {k: v for k, v in os.environ.items() if k != CONFIG_ENV}
    assert env == expected


def test_run_rg_argv_and_env(hostile_env, tmp_path, monkeypatch):
    seen = Captured()

    def fake_run(cmd, **kw):
        seen.calls.append((cmd, kw.get("env")))
        return subprocess.CompletedProcess(cmd, 1, "", "")

    monkeypatch.setattr(str_rg.subprocess, "run", fake_run)
    str_rg.run_rg(tmp_path, "x", True, 2, rg_bin="rg", timeout_s=5)
    ((argv, env),) = seen.calls
    assert_scrubbed(argv, env)


def test_stream_argv_and_env(hostile_env, tmp_path, monkeypatch):
    seen = Captured()
    real_popen = subprocess.Popen

    def fake_popen(cmd, **kw):
        seen.calls.append((cmd, kw.get("env")))
        return real_popen(["true"], **kw)

    monkeypatch.setattr(sts.subprocess, "Popen", fake_popen)
    stream = sts.RgJsonStream(tmp_path, "x", True, 2, rg_bin="rg", timeout_s=5)
    with sts.managed_rg_stream(stream):
        list(stream)
    ((argv, env),) = seen.calls
    assert_scrubbed(argv, env)
    assert stream._command()[1] == NO_CONFIG


def test_list_files_glob_argv_and_env(hostile_env, tmp_path, monkeypatch):
    seen = Captured()

    def fake_run(cmd, **kw):
        seen.calls.append((cmd, kw.get("env")))
        return subprocess.CompletedProcess(cmd, 1, "", "")

    monkeypatch.setattr(lf.subprocess, "run", fake_run)
    for hidden in (False, True):
        lf._glob_mode(tmp_path, "*.txt", 10, hidden, rg_bin="rg", timeout_s=5)
    assert len(seen.calls) == 2
    for argv, env in seen.calls:
        assert_scrubbed(argv, env)


def test_rg_rejection_argv_and_env(hostile_env, monkeypatch):
    seen = Captured()

    def fake_run(cmd, **kw):
        seen.calls.append((cmd, kw.get("env")))
        return subprocess.CompletedProcess(cmd, 2, "", "regex parse error")

    class Search:
        _rg_bin = "rg"

    class Access:
        search = Search()

    monkeypatch.setattr(stc.subprocess, "run", fake_run)
    error = stc._rg_rejection(Access(), "(", False)
    assert isinstance(error, CodedToolError)
    ((argv, env),) = seen.calls
    assert_scrubbed(argv, env)


def test_every_linux_rg_call_site_uses_the_helper():
    """Sweep: a features module that starts a process with an rg binary
    must import the config-free helper (Darwin adapters are out of scope)."""
    features = Path(st.__file__).resolve().parents[2]
    offenders = []
    for path in sorted(features.rglob("*.py")):
        text = path.read_text()
        starts = "subprocess.run(" in text or "subprocess.Popen(" in text
        uses_rg = "rg_bin" in text
        helper = "from binnacle.features.search.rg_env import" in text
        if starts and uses_rg and not helper:
            offenders.append(str(path.relative_to(features)))
    assert offenders == []
