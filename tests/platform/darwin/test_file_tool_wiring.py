"""Descriptor tool integration: moved roots, refusal and deterministic teardown."""

import asyncio
from pathlib import Path

import pytest
from fastmcp import Client

from binnacle.application import compose_native_tools, create_application
from binnacle.config import RootsSettings, Settings
from binnacle.features.commands.restricted_backend import RestrictedCommandBackend
from binnacle.features.files import paths
from binnacle.platform.contracts.capability_contracts import Capability, CapabilityState
from binnacle.platform.darwin.file_access import DarwinFileAccess
from binnacle.platform.darwin.search_access import DarwinSearchAccess


def test_all_five_tools_keep_opened_root_after_rename(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    (root / "sample.txt").write_text("hello needle\n")
    settings = Settings(roots=RootsSettings(default_root=root, extra_roots=()))
    files = DarwinFileAccess()
    search = DarwinSearchAccess(files, rg_bin="rg")
    # Explicit harness injection qualifies wiring, never public runtime acceptance.
    access_type = getattr(paths, "FileToolAccess", None)
    assert access_type is not None, "descriptor wiring is missing"
    access = access_type(
        roots=settings.roots,
        files=files,
        search=search,
        generation="test-generation",
        capability=Capability(CapabilityState.LIMITED, "test_only", "opened-object"),
    )
    app = create_application(
        settings=settings,
        token="test",
        backend=RestrictedCommandBackend(),
        file_access=access,
    )
    root.rename(tmp_path / "moved")
    root.mkdir()
    (root / "sample.txt").write_text("UNAUTHORIZED replacement\n")

    def forbidden(*args, **kwargs):
        raise AssertionError("legacy pathname authority used")

    monkeypatch.setattr(paths, "resolve_path", forbidden)
    from binnacle.features.files.tools import (
        edit_file,
        list_files,
        read_file,
        write_file,
    )
    from binnacle.features.search.tools import search_text

    for module in (read_file, list_files, write_file, edit_file, search_text):
        monkeypatch.setattr(module, "resolve_path", forbidden)

    async def exercise():
        async with Client(app) as client:
            read = await client.call_tool(
                "read_file", {"path": str(root / "sample.txt")}
            )
            assert read.structured_content["content"] == "hello needle\n"
            listing = await client.call_tool("list_files", {"path": str(root)})
            assert listing.structured_content["count"] == 1
            write = await client.call_tool(
                "write_file",
                {"path": str(root / "new/f.txt"), "content": "old needle\n"},
            )
            assert write.structured_content["action"] == "created"
            edit = await client.call_tool(
                "edit_file",
                {
                    "path": str(root / "new/f.txt"),
                    "old_string": "old",
                    "new_string": "new",
                },
            )
            assert edit.structured_content["replacements"] == 1
            nested = await client.call_tool("list_files", {"path": str(root / "new")})
            assert nested.structured_content["entries"][0]["path"] == str(
                root / "new/f.txt"
            )
            found = await client.call_tool(
                "search_text",
                {"path": str(root), "pattern": "needle", "context_lines": 0},
            )
            assert found.structured_content["count"] == 2

    asyncio.run(exercise())
    assert (tmp_path / "moved/new/f.txt").read_text() == "new needle\n"
    assert not (root / "new").exists()
    with pytest.raises(Exception, match="closed"):
        access.select(str(root / "sample.txt"))


def test_unreviewed_and_missing_provider_refuse_without_opening(tmp_path):
    access_type = getattr(paths, "FileToolAccess", None)
    assert access_type is not None, "descriptor wiring is missing"
    access = access_type(
        roots=RootsSettings(default_root=tmp_path, extra_roots=()),
        files=None,
        search=None,
        generation="test-generation",
        capability=Capability(
            CapabilityState.UNAVAILABLE, "review_pending", "opened-object"
        ),
    )
    with pytest.raises(Exception, match="native_capability_unavailable"):
        access.select("/outside/never-open")


@pytest.mark.parametrize(
    "name", ["read_file", "list_files", "write_file", "edit_file", "search_text"]
)
def test_all_tools_refuse_symlink_escape(tmp_path, name):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.txt").write_text("secret content")
    (root / "link").symlink_to(outside, target_is_directory=True)
    settings = Settings(roots=RootsSettings(default_root=root, extra_roots=()))
    files = DarwinFileAccess()
    access = paths.FileToolAccess(
        roots=settings.roots,
        files=files,
        search=DarwinSearchAccess(files, rg_bin="rg"),
        generation="test-symlink",
        capability=Capability(CapabilityState.LIMITED, "test_only", "opened-object"),
    )
    app = create_application(
        settings=settings,
        token="test",
        backend=RestrictedCommandBackend(),
        file_access=access,
    )
    args = {
        "read_file": {"path": str(root / "link/private.txt")},
        "list_files": {"path": str(root / "link")},
        "write_file": {
            "path": str(root / "link/private.txt"),
            "content": "overwritten",
        },
        "edit_file": {
            "path": str(root / "link/private.txt"),
            "old_string": "secret",
            "new_string": "changed",
        },
        "search_text": {"path": str(root / "link"), "pattern": "secret"},
    }

    async def check():
        async with Client(app) as client:
            result = await client.call_tool(name, args[name], raise_on_error=False)
            assert result.is_error
            assert "secret content" not in str(result.content)

    asyncio.run(check())
    assert (outside / "private.txt").read_text() == "secret content"


def test_failed_read_hint_stays_inside_grant_and_edit_conflict_is_preserved(
    tmp_path, monkeypatch
):
    from binnacle.errors import CodedToolError
    from binnacle.features.files.tools.edit_file import edit_file_impl

    (tmp_path / "file.txt").write_text("original")
    roots = RootsSettings(default_root=tmp_path, extra_roots=())
    files = DarwinFileAccess()
    access = paths.FileToolAccess(
        roots=roots,
        files=files,
        search=None,
        generation="test-conflict",
        capability=Capability(CapabilityState.LIMITED, "test_only", "opened-object"),
    )
    try:
        with pytest.raises(CodedToolError, match="Files in .*: file.txt"):
            access.read("missing.txt", 1024)
        read = access.read

        def racing_read(raw, max_bytes):
            value = read(raw, max_bytes)
            (tmp_path / "file.txt").write_text("concurrent change")
            return value

        monkeypatch.setattr(access, "read", racing_read)
        with pytest.raises(CodedToolError, match="conflict"):
            edit_file_impl(
                "file.txt",
                "original",
                "replacement",
                False,
                roots=roots,
                file_access=access,
            )
        assert (tmp_path / "file.txt").read_text() == "concurrent change"
    finally:
        access.close()


def test_descriptor_outputs_match_legacy_supported_text_subset(tmp_path):
    """Same-host differential check of Core formatting, not Linux OS evidence."""
    from binnacle.features.files.tools import (
        edit_file,
        list_files,
        read_file,
        write_file,
    )
    from binnacle.features.search.tools import search_text

    roots = RootsSettings(default_root=tmp_path, extra_roots=())
    files = DarwinFileAccess()
    access = paths.FileToolAccess(
        roots=roots,
        files=files,
        search=DarwinSearchAccess(files, rg_bin="rg"),
        generation="test-differential",
        capability=Capability(CapabilityState.LIMITED, "test_only", "opened-object"),
    )
    target = tmp_path / "sample.txt"
    original = "first\nneedle value\nlast\n"
    target.write_text(original)
    try:
        for function, args in [
            (read_file.read_file_impl, (str(target), 1, None)),
            (list_files.list_files_impl, (str(tmp_path), None, 100, False)),
            (
                search_text.search_text_impl,
                ("needle", str(tmp_path), None, False, 1, False, 100),
            ),
        ]:
            legacy = function(*args, roots=roots).structured_content
            native = function(*args, roots=roots, file_access=access).structured_content
            assert native == legacy
        legacy = edit_file.edit_file_impl(
            str(target), "value", "changed", False, roots=roots
        )
        target.write_text(original)
        native = edit_file.edit_file_impl(
            str(target), "value", "changed", False, roots=roots, file_access=access
        )
        assert native.structured_content == legacy.structured_content
        target.unlink()
        legacy = write_file.write_file_impl(str(target), original, roots=roots)
        target.unlink()
        native = write_file.write_file_impl(
            str(target), original, roots=roots, file_access=access
        )
        assert native.structured_content == legacy.structured_content
    finally:
        access.close()


def test_candidate_release_scope_is_per_tool_and_committed_scope_is_unchanged(
    tmp_path, monkeypatch
):
    from dataclasses import replace

    from binnacle.platform import composition
    from binnacle.platform.contracts.darwin_release_scope import DARWIN_RELEASE_SCOPE

    monkeypatch.setattr(composition.platform, "system", lambda: "Darwin")
    settings = Settings(roots=RootsSettings(default_root=tmp_path, extra_roots=()))
    (tmp_path / "file").write_text("hello")
    committed = dict(DARWIN_RELEASE_SCOPE)
    scope = {
        tool: replace(
            row, capability=Capability(CapabilityState.UNAVAILABLE, "test", tool)
        )
        for tool, row in committed.items()
    }
    limited = Capability(CapabilityState.LIMITED, "test_only", "read_file")
    scope["read_file"] = replace(scope["read_file"], capability=limited)
    access, backend = compose_native_tools(
        settings=settings, release_scope=scope, owner="embedded"
    )
    app = create_application(
        settings=settings, token="test", backend=backend, file_access=access
    )

    async def exercise():
        async with Client(app) as client:
            result = await client.call_tool(
                "read_file", {"path": str(tmp_path / "file")}
            )
            assert result.structured_content["content"] == "hello"
            for name, args in (
                ("write_file", {"path": str(tmp_path / "file"), "content": "bad"}),
                ("list_files", {"path": str(tmp_path)}),
                ("job_status", {}),
                ("stop_job", {"job_id": "foreign"}),
            ):
                result = await client.call_tool(name, args, raise_on_error=False)
                assert result.is_error and "unavailable" in str(result.content).lower()

    asyncio.run(exercise())
    assert (tmp_path / "file").read_text() == "hello"
    assert dict(DARWIN_RELEASE_SCOPE) == committed


def test_a6_service_output_uses_a5_redacted_epochs(tmp_path, monkeypatch):
    import logging
    import plistlib
    import sys
    import tempfile
    from pathlib import Path

    from binnacle.platform import composition

    with tempfile.TemporaryDirectory(
        prefix="b0log-", dir=Path("/tmp").resolve()
    ) as directory:
        tmp_path = Path(directory)
        monkeypatch.setattr(composition.platform, "system", lambda: "Darwin")
        # A6's actual plan carries the writer generation and never raw output files.
        lease = composition.create_service_lease(
            root=tmp_path,
            label="com.binnacle.r3test.probe",
            generation="service-output-123456",
        )
        provisioner = composition.create_native_provisioner(root=tmp_path, lease=lease)
        plan = provisioner.plan(
            lease, argv=["/usr/bin/true"], environment={}, workdir=tmp_path
        )
        plist = plistlib.loads(plan.plist_bytes)
        assert not {"StandardOutPath", "StandardErrorPath"} & plist.keys()
        for key, value in plist["EnvironmentVariables"].items():
            monkeypatch.setenv(key, value)
        with composition.native_service_output():
            print("password=", end="")
            print("topsecret-value")
            sys.stderr.write("token=other-secret\n")
            logging.getLogger("b0.service.test").warning("auth=private-value")
        source = composition.create_service_log_source(
            root=tmp_path, generation=lease.generation
        )
        batch = source.read_cursor("probe", None, max_bytes=4096, max_lines=20)
        assert b"[redacted]" in batch.data
        for path in tmp_path.rglob("*"):
            if path.is_file():
                assert not any(
                    secret in path.read_bytes()
                    for secret in (
                        b"topsecret-value",
                        b"other-secret",
                        b"private-value",
                    )
                )


def test_search_reads_files_over_the_budget_whole_without_schema_change(tmp_path):
    from binnacle.features.search.tools.search_text import search_text_impl

    (tmp_path / "small.txt").write_text("needle\n")
    (tmp_path / "large.txt").write_bytes(b"x" * (16 * 1024 * 1024 + 1))
    roots = RootsSettings(default_root=tmp_path, extra_roots=())
    files = DarwinFileAccess()
    access = paths.FileToolAccess(
        roots=roots,
        files=files,
        search=DarwinSearchAccess(files, rg_bin="rg"),
        generation="summary-test",
        capability=Capability(CapabilityState.LIMITED, "test", "opened-object"),
    )
    try:
        result = search_text_impl(
            "needle",
            str(tmp_path),
            None,
            False,
            0,
            False,
            100,
            roots=roots,
            file_access=access,
        )
        # Linux searches the >16 MiB file whole (Pi CASES.json st.basic, fx.big).
        assert result.structured_content["count"] == 1
        assert result.structured_content["truncated"] is False
        assert (
            result.content[0].text == f"Found 1 matches for 'needle' under {tmp_path}."
        )
        assert set(result.structured_content) == {
            "path",
            "pattern",
            "entries",
            "count",
            "truncated",
        }
    finally:
        access.close()


def _symlink_app(tmp_path):
    """Granted root with every symlink shape; Linux-measured expectations below."""
    import os

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("outside-secret\n")
    (outside / "dir").mkdir()
    root = tmp_path / "root"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "sub").mkdir()
    (root / "hello.txt").write_text("hello\n")
    (root / "docs" / "note.md").write_text("hi")
    links = {
        "filelink": "hello.txt",
        "dirlink": "docs",
        "docs/uplink": "../hello.txt",
        "chain": "filelink",
        "outfile": "../outside/secret.txt",
        "outdir": "../outside/dir",
        "abs_out": str(outside / "secret.txt"),
        "abs_in": str(root / "hello.txt"),
        "dangling": "missing",
        "loop": "loop",
        "docs/escape": "../../outside/secret.txt",
    }
    for name, target in links.items():
        (root / name).symlink_to(target)
    os.mkfifo(root / "fifo")
    settings = Settings(roots=RootsSettings(default_root=root, extra_roots=()))
    files = DarwinFileAccess()
    access = paths.FileToolAccess(
        roots=settings.roots,
        files=files,
        search=DarwinSearchAccess(files, rg_bin="rg"),
        generation="test-generation",
        capability=Capability(CapabilityState.LIMITED, "test_only", "opened-object"),
    )
    app = create_application(
        settings=settings,
        token="test",
        backend=RestrictedCommandBackend(),
        file_access=access,
    )
    return app, root, files


def _list(app, *calls):
    """One client session per app: closing it releases the opened root grants."""

    async def call():
        async with Client(app) as client:
            return [
                (await client.call_tool("list_files", args)).structured_content
                for args in calls
            ]

    return asyncio.run(call())


def test_list_files_symlinks_match_linux_for_in_root_and_omit_the_rest(tmp_path):
    app, root, files = _symlink_app(tmp_path)
    try:
        listing, sub = _list(app, {"path": str(root)}, {"path": str(root / "docs")})
        assert listing["mode"] == "list"
        # Linux types a symlink by its target. Outside-root, absolute, dangling,
        # looping and special entries are omitted (deliberate divergence).
        assert [(e["path"], e["type"], e.get("bytes")) for e in listing["entries"]] == [
            (str(root / "dirlink"), "dir", None),
            (str(root / "docs"), "dir", None),
            (str(root / "chain"), "file", 6),
            (str(root / "filelink"), "file", 6),
            (str(root / "hello.txt"), "file", 6),
        ]
        for entry in listing["entries"] + sub["entries"]:  # never mistyped
            if (link := Path(entry["path"])).is_symlink():
                assert link.resolve().is_relative_to(root.resolve()), entry
                assert entry["type"] == ("dir" if link.is_dir() else "file")
        assert {(e["path"], e["type"]) for e in sub["entries"]} == {
            (str(root / "docs/note.md"), "file"),
            (str(root / "docs/sub"), "dir"),
            (str(root / "docs/uplink"), "file"),
        }
    finally:
        files.close()


@pytest.mark.parametrize("glob", ["*", "**/*", "*link"])
def test_list_files_glob_omits_symlinks_and_special_files(tmp_path, glob):
    app, root, files = _symlink_app(tmp_path)
    try:
        (listing,) = _list(app, {"path": str(root), "glob": glob})
        assert listing["mode"] == "glob"
        names = {e["path"] for e in listing["entries"]}
        assert all(e["type"] == "file" for e in listing["entries"])
        for omitted in ("filelink", "dirlink", "chain", "fifo", "dangling", "outfile"):
            assert str(root / omitted) not in names
            assert not any(n.startswith(str(root / "dirlink") + "/") for n in names)
        if glob != "*link":
            assert str(root / "hello.txt") in names
    finally:
        files.close()
