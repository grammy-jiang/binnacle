"""read_file verify-after-open on Linux (r6 W2 X3b, SD-76).

read_file resolves a path, checks that it lies in a configured root and
stats it. X3b then opens that object through the descriptor walk
(fd_walk.open_walked) and verifies the opened descriptor: its kernel path
is inside SOME configured root, its (st_dev, st_ino) is the pair from the
check, it is a regular file and it still has a link. The content is read
only from that descriptor. The race tests swap the object between the check
and the open: r6 (b18521f) reads the swapped object, X3b refuses. This is
not confinement: every path whose target lies in any root reads as in r6.
"""

import os
import stat
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from binnacle.config import ReadFileSettings, RootsSettings
from binnacle.errors import CodedToolError
from binnacle.features.files.tools import read_file as rf

# The process descriptor table: /proc/self/fd on Linux, /dev/fd on Darwin.
FD_DIR = "/proc/self/fd" if os.path.isdir("/proc/self/fd") else "/dev/fd"

try:
    from binnacle.features.files import fd_walk
except ImportError:  # The r6 base (b18521f) has no descriptor walk.
    fd_walk = None  # type: ignore[assignment]

SECRET = "s" * 4321  # A size and text that appear nowhere else in the fixture.
not_root = pytest.mark.skipif(os.geteuid() == 0, reason="root ignores modes")
x3b_only = pytest.mark.skipif(
    fd_walk is None or not hasattr(fd_walk, "open_walked"),
    reason="the hook point exists only with the X3b walk",
)
# Linux-only mechanism: read_file_impl without file_access over fd_walk;
# Darwin reads through DarwinFileAccess (test_r6w2_t3_special_files.py).
LINUX_READ = pytest.mark.skipif(
    sys.platform != "linux", reason="Linux read path (fd_walk.open_walked)"
)


@pytest.fixture
def tree(tmp_path: Path) -> dict:
    base = tmp_path.resolve()
    root, out = base / "root", base / "out"
    (root / "d").mkdir(parents=True)
    out.mkdir()
    (root / "d" / "f.txt").write_text("checked")
    (root / "other.txt").write_text("other")
    (out / "secret.txt").write_text(SECRET)
    (out / "f.txt").write_text(SECRET)
    return {
        "base": base,
        "root": root,
        "out": out,
        "file": root / "d" / "f.txt",
        "roots": RootsSettings(default_root=root, extra_roots=()),
    }


def outcome(roots: RootsSettings, path: Path) -> tuple[str, str]:
    """('read', content) or ('refused', code); a refusal never shows SECRET."""
    try:
        payload = rf.read_file_impl(str(path), 1, None, roots=roots).structured_content
    except ToolError as exc:
        assert isinstance(exc, CodedToolError)
        assert SECRET not in str(exc)
        return "refused", exc.telemetry_code
    assert payload is not None
    return "read", payload.get("content", payload["kind"])


def before_open(monkeypatch, target: Path, action: Callable[[], None]) -> list[int]:
    """Run action once, after the containment check, before the open.

    r6 opens with Path.read_bytes; X3b opens with fd_walk.open_walked. Both
    are hooked, so the same test shows r6 vs X3b.
    """
    fired: list[int] = []

    def once() -> None:
        if not fired:
            fired.append(1)
            action()

    real_read_bytes = Path.read_bytes

    def read_bytes(self: Path) -> bytes:
        if self == target:
            once()
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    if fd_walk is not None and hasattr(fd_walk, "open_walked"):
        real_walked = fd_walk.open_walked

        def walked(*args, **kwargs) -> int:
            once()
            return real_walked(*args, **kwargs)

        monkeypatch.setattr(fd_walk, "open_walked", walked)
    return fired


def after_open(monkeypatch, action: Callable[[], None]) -> list[int]:
    """Run action once, right after the final open, before verification."""
    fired: list[int] = []
    real = fd_walk._opened_path

    def hooked(fd: int) -> str:
        if not fired:
            fired.append(1)
            action()
        return real(fd)

    monkeypatch.setattr(fd_walk, "_opened_path", hooked)
    return fired


def swap_in(target: Path, make: Callable[[Path], object]) -> Callable[[], None]:
    """Replace target atomically with the object make() builds beside it."""

    def action() -> None:
        tmp = target.with_name(target.name + ".new")
        make(tmp)
        os.replace(tmp, target)

    return action


def outside_opens(monkeypatch, roots: tuple[Path, ...]) -> list[str]:
    """Record the kernel path of every fd the read opens outside the roots."""
    seen: list[str] = []
    real_open = os.open

    def record(path, flags, *args, **kwargs):
        fd = real_open(path, flags, *args, **kwargs)
        real = Path(os.readlink(f"/proc/self/fd/{fd}"))
        inside = any(real.is_relative_to(r) for r in roots)
        ancestor = any(r.is_relative_to(real) for r in roots)  # '/' included
        if not inside and not ancestor:
            seen.append(str(real))
        return fd

    monkeypatch.setattr(os, "open", record)
    return seen


def test_an_unraced_read_is_unchanged(tree):
    assert outcome(tree["roots"], tree["file"]) == ("read", "checked")


# Swaps between the containment check and the open (r6 reads the swap).


@LINUX_READ
def test_a_final_symlink_to_an_outside_file_is_refused(tree, monkeypatch):
    link = swap_in(tree["file"], lambda tmp: tmp.symlink_to(tree["out"] / "secret.txt"))
    fired = before_open(monkeypatch, tree["file"], link)
    assert outcome(tree["roots"], tree["file"]) == ("refused", "path_outside_root")
    assert fired


@LINUX_READ
def test_a_final_symlink_to_another_in_root_file_is_refused(tree, monkeypatch):
    link = swap_in(tree["file"], lambda tmp: tmp.symlink_to(tree["root"] / "other.txt"))
    fired = before_open(monkeypatch, tree["file"], link)
    assert outcome(tree["roots"], tree["file"]) == ("refused", "path_changed")
    assert fired


@LINUX_READ
def test_a_different_in_root_file_is_refused(tree, monkeypatch):
    other = swap_in(tree["file"], lambda tmp: tmp.write_text("swapped"))
    fired = before_open(monkeypatch, tree["file"], other)
    assert outcome(tree["roots"], tree["file"]) == ("refused", "path_changed")
    assert fired


@LINUX_READ
def test_a_hard_link_to_an_outside_file_is_refused(tree, monkeypatch):
    # The swapped object's kernel path is in the root; the identity is not.
    hard = swap_in(tree["file"], lambda tmp: os.link(tree["out"] / "secret.txt", tmp))
    fired = before_open(monkeypatch, tree["file"], hard)
    assert outcome(tree["roots"], tree["file"]) == ("refused", "path_changed")
    assert fired


@LINUX_READ
def test_a_parent_symlink_to_an_outside_dir_opens_nothing_outside(tree, monkeypatch):
    # RX3a2-N2: the walk fails at the swapped component (no-follow), so the
    # outside file is never opened; the refusal still names it outside.
    def swap_parent() -> None:
        os.rename(tree["root"] / "d", tree["base"] / "d.old")
        (tree["root"] / "d").symlink_to(tree["out"], target_is_directory=True)

    fired = before_open(monkeypatch, tree["file"], swap_parent)
    seen = outside_opens(monkeypatch, (tree["root"],))
    assert outcome(tree["roots"], tree["file"]) == ("refused", "path_outside_root")
    assert fired and seen == []


@LINUX_READ
@pytest.mark.timeout(10)  # r6 blocks in open(2) on the FIFO without a writer.
def test_a_fifo_swapped_in_is_refused_by_type_first(tree, monkeypatch):
    # Checks run root -> type -> identity on both OSes (FDW-B1-a2 R1, SD-91):
    # a FIFO is special_file_unsupported even when it is another object.
    fifo = swap_in(tree["file"], os.mkfifo)
    fired = before_open(monkeypatch, tree["file"], fifo)
    assert outcome(tree["roots"], tree["file"]) == (
        "refused",
        "special_file_unsupported",
    )
    assert fired


@LINUX_READ
@pytest.mark.timeout(10)
def test_a_checked_fifo_is_not_a_regular_file(tree):
    fifo = tree["root"] / "fifo"
    os.mkfifo(fifo)
    # X3b-a3: Darwin's code for a FIFO, socket or device.
    assert outcome(tree["roots"], fifo) == ("refused", "special_file_unsupported")


# Changes after the open, before the verification (X3b only).


@LINUX_READ
@x3b_only
def test_a_file_renamed_out_of_every_root_after_the_open_is_refused(tree, monkeypatch):
    fired = after_open(
        monkeypatch, lambda: os.rename(tree["root"] / "d", tree["out"] / "moved")
    )
    assert outcome(tree["roots"], tree["file"]) == ("refused", "path_outside_root")
    assert fired


@LINUX_READ
@x3b_only
def test_a_file_deleted_after_the_open_is_path_changed(tree, monkeypatch):
    # The st_nlink == 0 rule: the named file no longer exists, so its content
    # is not served; a new call reports file_not_found.
    fired = after_open(monkeypatch, tree["file"].unlink)
    assert outcome(tree["roots"], tree["file"]) == ("refused", "path_changed")
    assert fired
    assert outcome(tree["roots"], tree["file"]) == ("refused", "file_not_found")


@x3b_only
def test_a_hard_linked_file_still_reads(tree):
    os.link(tree["file"], tree["root"] / "twin.txt")
    assert outcome(tree["roots"], tree["file"]) == ("read", "checked")


@LINUX_READ
@x3b_only
def test_the_root_check_runs_before_the_identity_check(tree, monkeypatch):
    other = swap_in(tree["file"], lambda tmp: tmp.write_text("swapped"))
    before_open(monkeypatch, tree["file"], other)
    after_open(monkeypatch, lambda: os.rename(tree["root"] / "d", tree["out"] / "m"))
    assert outcome(tree["roots"], tree["file"]) == ("refused", "path_outside_root")


@LINUX_READ
@x3b_only
@pytest.mark.timeout(10)
def test_the_root_check_runs_before_the_type_check(tree, monkeypatch):
    # read_file_impl refuses a FIFO by its pre-open stat (r6 W3 RF1,
    # SRC-W2-01), so the race step is called directly.
    os.mkfifo(tree["root"] / "d" / "fifo")
    after_open(monkeypatch, lambda: os.rename(tree["root"] / "d", tree["out"] / "m"))
    fifo = tree["root"] / "d" / "fifo"
    info = os.lstat(fifo)
    with pytest.raises(CodedToolError) as exc:
        rf._read_checked(
            fifo, (info.st_dev, info.st_ino), tree["roots"], ReadFileSettings()
        )
    assert exc.value.telemetry_code == "path_outside_root"


@x3b_only
def test_the_content_comes_only_from_the_verified_fd(tree, monkeypatch):
    real_walked = fd_walk.open_walked

    def walked_then_swap(*args, **kwargs) -> int:
        fd = real_walked(*args, **kwargs)
        swap_in(tree["file"], lambda tmp: tmp.write_text(SECRET))()
        return fd

    monkeypatch.setattr(fd_walk, "open_walked", walked_then_swap)
    assert outcome(tree["roots"], tree["file"]) == ("read", "checked")


@LINUX_READ
@x3b_only
def test_the_walk_traverses_no_follow_and_opens_the_name_once(tree, monkeypatch):
    calls: list[tuple[str, int, int | None]] = []
    real_open = os.open

    def record(path, flags, *args, dir_fd=None, **kwargs):
        calls.append((os.fspath(path), flags, dir_fd))
        return real_open(path, flags, *args, dir_fd=dir_fd, **kwargs)

    monkeypatch.setattr(fd_walk.os, "open", record)
    assert outcome(tree["roots"], tree["file"]) == ("read", "checked")
    *walk, final = calls
    assert final[:2] == ("f.txt", fd_walk.READ_FLAGS) and final[2] is not None
    assert walk[0] == ("/", fd_walk.TRAVERSE_FLAGS, None)
    assert all(flags == fd_walk.TRAVERSE_FLAGS for _, flags, _ in walk)
    assert all(fd is not None for _, _, fd in walk[1:])
    assert not any(name == str(tree["file"]) for name, _, _ in calls)


@LINUX_READ
@x3b_only
def test_refusals_leak_no_descriptor(tree, monkeypatch):
    before = len(os.listdir(FD_DIR))
    link = swap_in(tree["file"], lambda tmp: tmp.symlink_to(tree["out"] / "secret.txt"))
    for _ in range(20):
        (tree["root"] / "d" / "f.txt").unlink(missing_ok=True)
        (tree["root"] / "d" / "f.txt").write_text("checked")
        monkeypatch.undo()
        before_open(monkeypatch, tree["file"], link)
        assert outcome(tree["roots"], tree["file"])[0] == "refused"
    assert len(os.listdir(FD_DIR)) == before


# SD-76: model-visible behavior stays as in r6.


@pytest.fixture
def nested(tmp_path: Path) -> dict:
    base = tmp_path.resolve()
    outer, other = base / "outer", base / "other"
    inner = outer / "inner"
    inner.mkdir(parents=True)
    other.mkdir()
    (outer / "o.txt").write_text("outer")
    (other / "x.txt").write_text("other root")
    (inner / "cross").symlink_to(other / "x.txt")
    (inner / "up").symlink_to("../o.txt")
    roots = RootsSettings(default_root=inner, extra_roots=(outer, other))
    return {"outer": outer, "inner": inner, "other": other, "roots": roots}


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("cross", "other root"),  # a link into another root
        ("up", "outer"),  # a link with '..' into an outer root
        ("../o.txt", "outer"),  # '..' in the request into an outer root
    ],
)
def test_targets_in_any_root_read_as_in_r6(nested, name, content):
    assert outcome(nested["roots"], nested["inner"] / name) == ("read", content)


def test_a_path_outside_every_root_is_the_r6_refusal(nested, tmp_path):
    outside = tmp_path.resolve() / "secret.txt"
    outside.write_text(SECRET)
    (nested["inner"] / "away").symlink_to(outside)
    for path in (outside, nested["inner"] / "away"):
        assert outcome(nested["roots"], path) == ("refused", "path_outside_root")


@not_root
def test_an_execute_only_directory_still_reads(tree):
    d = tree["root"] / "d"
    d.chmod(stat.S_IXUSR)
    try:
        assert outcome(tree["roots"], tree["file"]) == ("read", "checked")
    finally:
        d.chmod(0o755)


# open_walked and the Darwin guard (RX3a2-N2, N4).


def ident(path: Path) -> tuple[int, int]:
    info = os.lstat(path)
    return info.st_dev, info.st_ino


@LINUX_READ
@x3b_only
def test_open_walked_opens_nothing_for_a_path_outside_every_root(tree, monkeypatch):
    opened: list[object] = []
    monkeypatch.setattr(fd_walk.os, "open", lambda *a, **k: opened.append(a))
    sibling = tree["base"] / "rootX" / "p"
    for path in (tree["out"] / "secret.txt", sibling):
        with pytest.raises(CodedToolError) as exc:
            fd_walk.open_walked(path, (tree["root"],), (0, 0))
        assert exc.value.telemetry_code == "path_outside_root"
    with pytest.raises(CodedToolError) as exc:
        fd_walk.open_walked(tree["root"], (tree["root"],), ident(tree["root"]))
    assert exc.value.telemetry_code == "path_is_directory"
    assert "Use list_files to browse it." in str(exc.value)
    assert opened == []


@x3b_only
@pytest.mark.parametrize("opener", ["open_verified", "open_walked"])
def test_open_verified_never_runs_off_linux(tree, monkeypatch, opener):
    opened: list[object] = []
    monkeypatch.setattr(fd_walk.os, "open", lambda *a, **k: opened.append(a))
    monkeypatch.setattr(fd_walk.sys, "platform", "darwin")
    extra = {"parent_fd": -1} if opener == "open_verified" else {}  # SRC-W2-03
    with pytest.raises(RuntimeError, match="Linux-only"):
        getattr(fd_walk, opener)(
            tree["file"], (tree["root"],), ident(tree["file"]), **extra
        )
    assert opened == []


@x3b_only
def test_darwin_read_file_never_calls_the_linux_opener(tree, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("open_verified is Linux-only")

    monkeypatch.setattr(fd_walk, "open_walked", forbidden)
    monkeypatch.setattr(fd_walk, "open_verified", forbidden)
    monkeypatch.setattr(rf.sys, "platform", "darwin")
    assert outcome(tree["roots"], tree["file"]) == ("read", "checked")
