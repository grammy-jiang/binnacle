"""Private Linux Bubblewrap argv construction, no process execution in these tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from binnacle.features.development_intelligence import lsp_linux_bwrap as wrapper


@pytest.fixture
def admitted_paths(tmp_path, monkeypatch):
    """Synthetic package outside operator root; bwrap is faked only for argv checks."""
    monkeypatch.setattr(wrapper.platform, "system", lambda: "Linux")
    original_is_file = Path.is_file
    monkeypatch.setattr(
        Path,
        "is_file",
        lambda path: path == wrapper._BWRAP or original_is_file(path),
    )
    original_access = wrapper.os.access
    monkeypatch.setattr(
        wrapper.os,
        "access",
        lambda path, mode: path == wrapper._BWRAP or original_access(path, mode),
    )
    package = tmp_path / "trusted" / "pyright"
    package.mkdir(parents=True)
    launcher = package / "langserver.index.js"
    launcher.write_text("#!/usr/bin/env node\n")
    (package / "package.json").write_text('{"name":"pyright"}')
    node = tmp_path / "trusted" / "node"
    node.write_bytes(b"\x7fELFsynthetic")
    workspace = tmp_path / "operator" / "source"
    workspace.mkdir(parents=True)
    return {"node": node, "launcher": launcher, "workspace": workspace}


def test_fixed_linux_mounts_and_no_host_home_credentials(admitted_paths):
    args = wrapper.build_private_bwrap_launch(**admitted_paths)
    root = str(admitted_paths["workspace"])
    package = str(admitted_paths["launcher"].parent)
    assert args[0] == str(wrapper._BWRAP)
    assert args[1:4] == ["--unshare-all", "--die-with-parent", "--clearenv"]
    assert "--new-session" not in args  # upstream already created one.
    binds = [
        args[i + 1 : i + 3] for i, token in enumerate(args[:-2]) if token == "--ro-bind"
    ]
    assert binds.count([root, root]) == 1
    assert binds.count([package, package]) == 1
    assert ["--bind", root, root] not in args
    assert "--bind" not in args and "--dev-bind" not in args
    assert "--tmpfs" in args and "--proc" in args and "--dev" in args
    assert "--clearenv" in args
    assert args[-4:] == [
        "--",
        "/opt/trusted-node",
        str(admitted_paths["launcher"]),
        "--stdio",
    ]
    assert ["/home", "/home"] not in binds


@pytest.mark.parametrize(
    "case",
    ["workspace_alias", "node_alias", "invalid_package", "workspace_in_package"],
)
def test_path_and_package_provenance_fail_closed(admitted_paths, case):
    paths = dict(admitted_paths)
    if case == "workspace_alias":
        link = paths["workspace"].parent / "alias"
        link.symlink_to(paths["workspace"], target_is_directory=True)
        paths["workspace"] = link
    elif case == "node_alias":
        alias = paths["node"].with_name("node-link")
        alias.symlink_to(paths["node"])
        paths["node"] = alias
    elif case == "invalid_package":
        (paths["launcher"].parent / "package.json").unlink()
    else:
        paths["workspace"] = paths["launcher"].parent
    with pytest.raises(wrapper.SandboxLaunchRefused):
        wrapper.build_private_bwrap_launch(**paths)


def test_system_tree_workspace_rejected(admitted_paths):
    with pytest.raises(wrapper.SandboxLaunchRefused, match="workspace_overlaps"):
        wrapper.build_private_bwrap_launch(
            **{**admitted_paths, "workspace": Path("/usr")}
        )


@pytest.mark.parametrize("mode", ["darwin", "missing_bwrap", "untrusted_bwrap"])
def test_unsupported_platform_or_bubblewrap_refuses(admitted_paths, monkeypatch, mode):
    if mode == "darwin":
        monkeypatch.setattr(wrapper.platform, "system", lambda: "Darwin")
        matched = "linux_bubblewrap_only"
    elif mode == "missing_bwrap":
        monkeypatch.setattr(wrapper.os, "access", lambda *args: False)
        matched = "trusted_bubblewrap_unavailable"
    else:
        with pytest.raises(
            wrapper.SandboxLaunchRefused, match="trusted_bubblewrap_unavailable"
        ):
            wrapper.build_private_bwrap_launch(
                **{**admitted_paths, "bwrap": admitted_paths["node"]}
            )
        return
    with pytest.raises(wrapper.SandboxLaunchRefused, match=matched):
        wrapper.build_private_bwrap_launch(**admitted_paths)


def test_private_owner_rejects_unknown_mode(tmp_path):
    from binnacle.config_development_intelligence import (
        DevelopmentIntelligenceSettings,
        DevelopmentProviderSettings,
    )
    from binnacle.features.development_intelligence.lsp_process_owner import (
        PrivatePyrightProcessOwner,
        ProviderLifecycleError,
    )

    root = tmp_path / "synthetic"
    root.mkdir()
    exe = tmp_path / "trusted"
    exe.write_text("never execute")
    profile = DevelopmentIntelligenceSettings(
        enabled=True,
        profiles={
            "pyright": DevelopmentProviderSettings(
                enabled=True,
                mode="explicit_trust_only",
                source="trusted_absolute",
                executable=str(exe),
            )
        },
    )
    with pytest.raises(ProviderLifecycleError, match="unreviewed_private_sandbox"):
        PrivatePyrightProcessOwner(
            profile,
            root,
            operator_allowed_roots=(root,),
            sandbox_mode="untrusted",
        )


@pytest.mark.parametrize("case", ["workspace-not-directory", "node-inside-workspace"])
def test_non_directory_or_workspace_executable_is_rejected(admitted_paths, case):
    paths = dict(admitted_paths)
    if case == "workspace-not-directory":
        workspace = paths["workspace"]
        workspace.rmdir()
        workspace.write_text("not a directory")
        reason = "sandbox_input_unavailable"
    else:
        node = paths["workspace"] / "node"
        node.write_bytes(b"\x7fELFsynthetic")
        paths["node"] = node
        reason = "node_inside_workspace"
    with pytest.raises(wrapper.SandboxLaunchRefused, match=reason):
        wrapper.build_private_bwrap_launch(**paths)


def test_unexpected_system_alias_is_rejected(admitted_paths, monkeypatch):
    # A changed /bin alias must never become a sandbox link to an unknown tree.
    # Emulate the Linux alias on macOS, where /bin is a real directory.
    original_is_symlink = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: True if path == Path("/bin") else original_is_symlink(path),
    )
    original = wrapper.os.readlink
    monkeypatch.setattr(
        wrapper.os,
        "readlink",
        lambda path: "untrusted/bin" if Path(path) == Path("/bin") else original(path),
    )
    with pytest.raises(wrapper.SandboxLaunchRefused, match="unexpected_system_alias"):
        wrapper.build_private_bwrap_launch(**admitted_paths)


def test_non_symlink_system_directory_is_readonly(admitted_paths, monkeypatch):
    # Exercise the genuine-directory branch under a synthetic OS layout.
    original = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: False if path == Path("/bin") else original(path),
    )
    argv = wrapper.build_private_bwrap_launch(**admitted_paths)
    mounts = [
        argv[i + 1 : i + 3] for i, arg in enumerate(argv[:-2]) if arg == "--ro-bind"
    ]
    assert ["/bin", "/bin"] in mounts
