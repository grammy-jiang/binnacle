"""Experimental Linux-only private Pyright launch wrapper using Bubblewrap.

This is a *launch-path prototype*, not a READ security certificate.
Never accept arbitrary bwrap arguments, root aliases or parent environment.
"""

from __future__ import annotations

import os
import platform
from pathlib import Path

# Fixed system executable: no PATH discovery, caller-specified command or shell.
_BWRAP = Path("/usr/bin/bwrap")
_FORBIDDEN_WORKSPACE_PREFIXES = (
    Path("/usr"),
    Path("/etc"),
    Path("/proc"),
    Path("/dev"),
    Path("/sys"),
    Path("/run"),
    Path("/opt"),
    Path("/bin"),
    Path("/sbin"),
    Path("/lib"),
    Path("/lib64"),
)


class SandboxLaunchRefused(ValueError):
    """The private experimental policy could not be assembled safely."""


def _parents(path: Path) -> set[Path]:
    return {ancestor for ancestor in path.parents if ancestor != Path("/")}


def _is_under(path: Path, prefix: Path) -> bool:
    return path == prefix or path.is_relative_to(prefix)


def _inside_bwrap_mount_dirs(package: Path, workspace: Path) -> list[str]:
    """Create only empty destination parents; no host home/credential bind."""
    needed = _parents(package) | _parents(workspace)
    # /usr and its common symlink aliases are provided by the fixed system
    # read-only mount, while /tmp is a private tmpfs.
    return [
        str(path)
        for path in sorted(needed, key=lambda item: (len(item.parts), str(item)))
        if path not in (Path("/usr"), Path("/tmp"))
        and not _is_under(path, Path("/usr"))
    ]


def build_private_bwrap_launch(
    *,
    node: Path,
    launcher: Path,
    workspace: Path,
    bwrap: Path = _BWRAP,
) -> list[str]:
    """Build a constant-policy argv for a trusted, *synthetic only* workspace.

    Caller must first admit launcher and sibling native Node through P3.3.
    The executable and package tree remain operator-trusted. Bwrap may not be
    accepted as isolation proof simply because this argv exists.
    """
    if platform.system() != "Linux" or os.name != "posix":
        raise SandboxLaunchRefused("linux_bubblewrap_only")
    if bwrap != _BWRAP or not bwrap.is_file() or not os.access(bwrap, os.X_OK):
        raise SandboxLaunchRefused("trusted_bubblewrap_unavailable")
    for path in (node, launcher, workspace):
        if not path.is_absolute() or path.resolve(strict=True) != path:
            raise SandboxLaunchRefused("noncanonical_sandbox_path")
    if not node.is_file() or not launcher.is_file() or not workspace.is_dir():
        raise SandboxLaunchRefused("sandbox_input_unavailable")
    package = launcher.parent
    if (
        launcher.name != "langserver.index.js"
        or not (package / "package.json").is_file()
    ):
        raise SandboxLaunchRefused("unsupported_pyright_package_layout")
    if any(_is_under(workspace, prefix) for prefix in _FORBIDDEN_WORKSPACE_PREFIXES):
        raise SandboxLaunchRefused("workspace_overlaps_sandbox_system")
    if _is_under(workspace, package) or _is_under(package, workspace):
        raise SandboxLaunchRefused("workspace_overlaps_pyright_package")
    if _is_under(node, workspace):
        raise SandboxLaunchRefused("node_inside_workspace")
    # Only the one selected Node ELF and the single Pyright package directory
    # are made available; not their ancestor installation trees.
    args = [
        str(bwrap),
        "--unshare-all",
        # Upstream subprocess exec already calls setsid, verified by native
        # process-tree capture. A second session inside Bubblewrap would make
        # its own Node children look like group escapees to Binnacle.
        "--die-with-parent",
        "--clearenv",
        "--ro-bind",
        "/usr",
        "/usr",
    ]
    for name in ("bin", "lib", "lib64", "sbin"):
        system = Path("/") / name
        if system.is_symlink():
            target = os.readlink(system)
            # This policy only trusts Linux's conventional /usr aliases.
            if target not in ("usr/bin", "usr/lib", "usr/lib64", "usr/sbin"):
                raise SandboxLaunchRefused("unexpected_system_alias")
            args.extend(["--symlink", target, str(system)])
        elif system.is_dir():
            args.extend(["--ro-bind", str(system), str(system)])
    args += [
        "--dir",
        "/opt",
        "--ro-bind",
        str(node),
        "/opt/trusted-node",
        "--tmpfs",
        "/tmp",
    ]
    for parent in _inside_bwrap_mount_dirs(package, workspace):
        args.extend(["--dir", parent])
    args += [
        "--ro-bind",
        str(package),
        str(package),
        "--ro-bind",
        str(workspace),
        str(workspace),
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--setenv",
        "PATH",
        "/usr/bin",
        "--setenv",
        "HOME",
        "/tmp",
        "--chdir",
        str(workspace),
        "--",
        "/opt/trusted-node",
        str(launcher),
        "--stdio",
    ]
    return args
