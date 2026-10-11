"""read_file X3b follow-ups (r6 W2 X3b-a2, SD-77; R-X3b F2, F3, F4, F6).

F2: the identity that the walk verifies is the one from the checked stat,
not from a later stat, so a swap between the stat and the open-walk entry
is refused. F3: a successful read leaks no descriptor. F4: the identity
check compares st_dev as well as st_ino. F6: the read stops after
max_file_bytes + 1 bytes, so a file that grew after the stat is
file_too_large with the same text as a file that is too large at the stat.
"""

import os
import stat
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from fastmcp.exceptions import ToolError

from binnacle.config import ReadFileSettings, RootsSettings
from binnacle.errors import CodedToolError
from binnacle.features.files import fd_walk
from binnacle.features.files.tools import read_file as rf

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux read path")
SECRET = "s" * 4321  # A size and text that appear nowhere else in the fixture.


@pytest.fixture
def tree(tmp_path: Path) -> dict:
    base = tmp_path.resolve()
    root, out, other = base / "root", base / "out", base / "other"
    (root / "d").mkdir(parents=True)
    out.mkdir()
    other.mkdir()
    (root / "d" / "f.txt").write_text("checked")
    (root / "bin.dat").write_bytes(b"\x00\x01binary")
    (root / "empty.txt").write_text("")
    (other / "x.txt").write_text("other root")
    (root / "cross").symlink_to(other / "x.txt")
    (out / "secret.txt").write_text(SECRET)
    return {
        "root": root,
        "out": out,
        "file": root / "d" / "f.txt",
        "roots": RootsSettings(default_root=root, extra_roots=(other,)),
    }


def read(
    roots: RootsSettings, path: Path, settings: ReadFileSettings | None = None
) -> tuple[str, str]:
    """('read', content) or ('refused', code); a refusal never shows SECRET."""
    try:
        result = rf.read_file_impl(str(path), 1, None, roots=roots, settings=settings)
    except ToolError as exc:
        assert isinstance(exc, CodedToolError)
        assert SECRET not in str(exc)
        return "refused", exc.telemetry_code
    payload = result.structured_content
    assert payload is not None
    return "read", payload.get("content", payload["kind"])


def refusal(
    roots: RootsSettings, path: Path, settings: ReadFileSettings
) -> CodedToolError:
    with pytest.raises(CodedToolError) as caught:
        rf.read_file_impl(str(path), 1, None, roots=roots, settings=settings)
    return caught.value


class SwapAfterStat:
    """ReadFileSettings stand-in: the first max_file_bytes read swaps.

    read_file_impl reads max_file_bytes right after the checked stat and
    before the walk, so the swap lands between the two on any version
    (the R-X3b version-neutral race hook).
    """

    def __init__(self, action: Callable[[], None]) -> None:
        self._real = ReadFileSettings()
        self._action = action
        self.fired = 0

    def __getattr__(self, name: str) -> object:
        return getattr(self._real, name)

    @property
    def max_file_bytes(self) -> int:
        if not self.fired:
            self.fired += 1
            self._action()
        return self._real.max_file_bytes


def swap_in(target: Path, make: Callable[[Path], object]) -> Callable[[], None]:
    """Replace target atomically with the object make() builds beside it."""

    def action() -> None:
        tmp = target.with_name(target.name + ".new")
        make(tmp)
        os.replace(tmp, target)

    return action


# F2: a swap between the checked stat and the open-walk entry.


@pytest.mark.parametrize("swap", ["replaced_in_root", "hard_link_outside"])
def test_a_swap_after_the_checked_stat_is_refused(tree, swap):
    def make(tmp: Path) -> None:
        if swap == "replaced_in_root":
            tmp.write_text("swapped")
        else:  # A hard link to an outside inode (same filesystem).
            os.link(tree["out"] / "secret.txt", tmp)

    swapping = SwapAfterStat(swap_in(tree["file"], make))
    outcome = read(tree["roots"], tree["file"], cast(ReadFileSettings, swapping))
    assert outcome == ("refused", "path_changed")
    assert swapping.fired == 1


def test_the_walk_verifies_the_identity_of_the_checked_stat(tree, monkeypatch):
    checked = tree["file"].stat()
    seen: list[tuple[int, int]] = []
    real = fd_walk.open_walked

    def spy(path: Path, roots, expected: tuple[int, int]) -> int:
        seen.append(expected)
        return real(path, roots, expected)

    monkeypatch.setattr(fd_walk, "open_walked", spy)
    assert read(tree["roots"], tree["file"]) == ("read", "checked")
    assert seen == [(checked.st_dev, checked.st_ino)]


# F3: no descriptor leak on the success path.


def test_successful_reads_leak_no_descriptor(tree):
    paths = [
        tree["file"],
        tree["root"] / "bin.dat",
        tree["root"] / "empty.txt",
        tree["root"] / "cross",
    ]
    for path in paths:  # Warm imports and caches before the count.
        assert read(tree["roots"], path)[0] == "read"
    before = sorted(os.listdir("/proc/self/fd"))
    for _ in range(25):
        outcomes = [read(tree["roots"], path) for path in paths]
        assert outcomes == [
            ("read", "checked"),
            ("read", "binary"),
            ("read", ""),
            ("read", "other root"),
        ]
    assert sorted(os.listdir("/proc/self/fd")) == before


# F4: st_dev is part of the identity.


def fstat_with(monkeypatch, change: Callable[[os.stat_result], tuple]) -> list[int]:
    """Rewrite the fstat of a regular file; directories stay real."""
    calls: list[int] = []
    real = os.fstat

    def fake(fd: int) -> os.stat_result:
        info = real(fd)
        if not stat.S_ISREG(info.st_mode):
            return info
        calls.append(fd)
        return os.stat_result(change(info))

    monkeypatch.setattr(fd_walk.os, "fstat", fake)
    return calls


def test_a_different_st_dev_with_the_same_st_ino_is_refused(tree, monkeypatch):
    def other_device(info: os.stat_result) -> tuple:
        fields = list(info[:10])
        fields[stat.ST_DEV] = info.st_dev + 1
        return tuple(fields)

    calls = fstat_with(monkeypatch, other_device)
    assert read(tree["roots"], tree["file"]) == ("refused", "path_changed")
    assert calls


def test_the_same_st_dev_and_st_ino_still_read(tree, monkeypatch):
    # Control for the test above: the rewritten fstat alone does not refuse.
    calls = fstat_with(monkeypatch, lambda info: tuple(info[:10]))
    assert read(tree["roots"], tree["file"]) == ("read", "checked")
    assert calls


# F6: the read is bounded by max_file_bytes + 1.

LIMIT = 4096


def small() -> ReadFileSettings:
    """A 4 KiB limit whose window still shows a whole file in one call."""
    return ReadFileSettings(
        max_file_bytes=LIMIT,
        max_lines=10 * LIMIT,
        max_chars=10 * LIMIT,
        max_line_chars=10 * LIMIT,
    )


def grow_after_stat(target: Path, extra: int) -> SwapAfterStat:
    def action() -> None:
        with target.open("ab") as grown:
            grown.write(b"g" * extra)

    return SwapAfterStat(action)


def limited(stand_in: SwapAfterStat) -> ReadFileSettings:
    stand_in._real = small()
    return cast(ReadFileSettings, stand_in)


@pytest.mark.parametrize("extra", [1, 3 * LIMIT])
def test_a_file_that_grows_past_the_limit_after_the_stat_is_too_large(tree, extra):
    target = tree["root"] / "grows.txt"
    target.write_bytes(b"a" * LIMIT)
    growing = grow_after_stat(target, extra)
    grown = refusal(tree["roots"], target, limited(growing))
    assert growing.fired == 1
    assert grown.telemetry_code == "file_too_large"
    # The same code and text as a file that is that size at the stat.
    big = tree["root"] / "big.txt"
    big.write_bytes(b"a" * (LIMIT + extra))
    at_stat = refusal(tree["roots"], big, small())
    assert at_stat.telemetry_code == "file_too_large"
    assert str(grown) == str(at_stat)


def test_the_read_never_asks_for_more_than_the_limit_plus_one(tree, monkeypatch):
    target = tree["root"] / "grows.txt"
    target.write_bytes(b"a" * LIMIT)
    asked: list[int] = []
    real = os.fdopen

    class Recorded:
        def __init__(self, fd: int, *args, **kwargs) -> None:
            self._file = real(fd, *args, **kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *exc: object) -> None:
            self._file.close()

        def fileno(self) -> int:
            return self._file.fileno()

        def read(self, size: int = -1) -> bytes:
            asked.append(size)
            return self._file.read(size)

    monkeypatch.setattr(rf.os, "fdopen", Recorded)
    growing = grow_after_stat(target, 10 * LIMIT)
    assert refusal(tree["roots"], target, limited(growing)).telemetry_code == (
        "file_too_large"
    )
    assert asked == [LIMIT + 1]


def test_a_file_exactly_at_the_limit_still_reads(tree):
    target = tree["root"] / "exact.txt"
    target.write_bytes(b"a" * (LIMIT - 1) + b"\n")
    result = rf.read_file_impl(
        str(target), 1, None, roots=tree["roots"], settings=small()
    )
    payload = result.structured_content
    assert payload is not None
    assert payload["content"] == "a" * (LIMIT - 1) + "\n"
    assert payload["bytes"] == LIMIT
    assert payload["truncated"] is False


def test_a_file_that_grows_but_stays_within_the_limit_reads(tree):
    target = tree["root"] / "grows.txt"
    target.write_bytes(b"a" * (LIMIT - 10))
    growing = grow_after_stat(target, 10)
    outcome = read(tree["roots"], target, limited(growing))
    assert growing.fired == 1
    assert outcome == ("read", "a" * (LIMIT - 10) + "g" * 10)
