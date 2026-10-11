"""Linux-runnable coverage for the Darwin file-error wording module."""

from pathlib import Path

import pytest

from binnacle.features.files import error_text
from binnacle.platform.contracts.capability_contracts import NativeCapabilityError
from binnacle.platform.contracts.file_access_contracts import FileEntry, FileListing


def native(code: str) -> NativeCapabilityError:
    return NativeCapabilityError(code, None)  # type: ignore[arg-type]


class Files:
    def __init__(self, entries=(), error=None):
        self.entries = list(entries)
        self.error = error
        self.requests = []

    def list_entries(self, grant, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return FileListing(self.entries, False)


def call(code, tool, display, *, files=None, grants=(), rel="a/b.txt"):
    return error_text.linux_error(
        native(code),
        tool,
        files=files,
        grants=list(grants),
        allowed=[Path("/root-a"), Path("/root-b")],
        grant=object(),
        rel=rel,
        display=display,
    )


def test_outside_error_and_format_nearby():
    err = error_text.outside_error([Path("/a"), Path("/b")], Path("/c/d"))
    assert err.telemetry_code == "path_outside_root"
    assert "(/a, /b): /c/d" in str(err)
    assert error_text.format_nearby(Path("/p"), []) == " Directory /p is empty."
    many = [f"f{i}" for i in range(12)]
    text = error_text.format_nearby(Path("/p"), many)
    assert "f9 …." in text and "f10" not in text
    assert error_text.format_nearby(Path("/p"), ["x"]).endswith(
        "x. Use list_files for more."
    )


@pytest.mark.parametrize(
    "tool,code,text",
    [
        ("list_files", "directory_not_found", "Directory not found"),
        ("search_text", "path_not_found", "Path not found"),
        ("read_file", "file_not_found", "File not found"),
    ],
)
def test_missing_target_wording_per_tool(tool, code, text):
    err = call("path_not_found", tool, Path("/r/a/b.txt"))
    assert err is not None and err.telemetry_code == code
    assert str(err).startswith(f"{text}: /r/a/b.txt.")


def test_missing_target_lists_nearby_entries(tmp_path):
    (tmp_path / "linkdir").mkdir()
    files = Files(
        [
            FileEntry("a/zeta.txt", "file", 1, 1),
            FileEntry("a/sub", "directory", None, None),
            FileEntry("a/link", "other", None, None, target_kind="directory"),
            FileEntry("a/linkdir", "other", None, None),
            FileEntry("a/dangling", "other", None, None),
        ]
    )
    display = tmp_path / "missing.txt"
    err = call("file_not_found", "edit_file", display, files=files)
    assert err is not None and err.telemetry_code == "file_not_found"
    assert files.requests[0].relative_path == "a"
    assert f"Files in {tmp_path}: dangling, link/, linkdir/, sub/, zeta.txt." in str(
        err
    )
    assert str(err).endswith(" To create a new file, use write_file.")


@pytest.mark.parametrize("failure", [native("denied"), OSError("io")])
def test_missing_target_listing_failure_has_no_hint(failure):
    err = call("file_not_found", "read_file", Path("/r/x"), files=Files(error=failure))
    assert str(err) == "File not found: /r/x."


def test_missing_target_without_parts_has_no_hint():
    files = Files()
    err = call("file_not_found", "read_file", Path("/r"), files=files, rel="")
    assert str(err) == "File not found: /r."
    assert files.requests == []


def test_path_is_directory_wording():
    browse = call("path_is_directory", "read_file", Path("/r/d"))
    assert str(browse).endswith("Use list_files to browse it.")
    edit = call("path_is_directory", "edit_file", Path("/r/d"))
    assert str(edit) == "Path is a directory, not a file: /r/d."


def test_unrelated_code_is_not_reworded():
    assert call("too_large", "read_file", Path("/r/x")) is None


def test_symlink_outside_grants_is_outside_error(tmp_path):
    inside = tmp_path / "root"
    inside.mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    link = inside / "link"
    link.symlink_to(outside)
    err = call("symlink_or_wrong_path_type", "read_file", link, grants=[inside])
    assert err is not None and err.telemetry_code == "path_outside_root"
    assert str(outside.resolve()) in str(err)


def test_symlink_resolve_failure_returns_none(monkeypatch, tmp_path):
    def boom(self, strict=False):
        raise RuntimeError("loop")

    monkeypatch.setattr(Path, "resolve", boom)
    assert (
        call("symlink_or_wrong_path_type", "read_file", tmp_path, grants=[tmp_path])
        is None
    )


def test_wrong_type_inside_grant(tmp_path):
    file_path = tmp_path / "f.txt"
    file_path.write_text("x")
    err = call("symlink_or_wrong_path_type", "list_files", file_path, grants=[tmp_path])
    assert err is not None and err.telemetry_code == "path_is_file"
    assert str(err).endswith("Use read_file to read it.")

    child = file_path / "child.txt"
    err = call("symlink_or_wrong_path_type", "write_file", child, grants=[tmp_path])
    assert err is not None and err.telemetry_code == "write_failed"
    assert str(err) == f"Could not write {child}: File exists."

    assert (
        call("symlink_or_wrong_path_type", "read_file", file_path, grants=[tmp_path])
        is None
    )
    assert (
        call(
            "symlink_or_wrong_path_type",
            "write_file",
            tmp_path / "new",
            grants=[tmp_path],
        )
        is None
    )
