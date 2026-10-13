"""FDW swap/shortage cases shared by the XOS contract document.

These fixtures deliberately operate only inside the test-owned root.
"""

from __future__ import annotations

import errno
import os
import socket
from pathlib import Path
from typing import Any

FDW_CASES = {
    "fdw_read_swap_regular": ("read", "fdw/swap_regular.txt", None, "regular", 1),
    "fdw_read_swap_fifo": ("read", "fdw/swap_fifo.txt", None, "fifo", 1),
    "fdw_read_swap_dir": ("read", "fdw/swap_dir.txt", None, "dir", 1),
    "fdw_read_swap_socket": ("read", "fdw/swap_socket.txt", None, "socket", 1),
    "fdw_read_swap_symlink_in": (
        "read",
        "fdw/swap_symlink_in.txt",
        None,
        "symlink_in",
        1,
    ),
    "fdw_read_swap_symlink_out": (
        "read",
        "fdw/swap_symlink_out.txt",
        None,
        "symlink_out",
        1,
    ),
    "fdw_read_shortage": ("read", "a.txt", None, "shortage", None),
    "fdw_list_shortage_once": ("list", "sub", None, "shortage", 1),
    "fdw_list_shortage_twice": ("list", "sub", None, "shortage", None),
    "fdw_list_link_walk_shortage_once": ("list", "lnk", "sub", "shortage", 1),
    "fdw_list_link_walk_shortage_twice": ("list", "lnk", "sub", "shortage", None),
}


def _fdw_open(target: Path, name: str, hook: str, times: int | None) -> Any:
    """os.open that runs hook before opening name relative to a dir_fd."""
    real_open, fired = os.open, list[str]()

    def call(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        wanted = path == name and kwargs.get("dir_fd") is not None
        if wanted and (times is None or len(fired) < times):
            fired.append(path)
            if hook == "shortage":
                raise OSError(errno.EMFILE, os.strerror(errno.EMFILE))
            if hook == "regular":  # os.replace of a file that exists: a new inode.
                incoming = target.with_name("incoming.txt")
                incoming.write_text("swapped in\n", encoding="utf-8")
                os.replace(incoming, target)
                return real_open(path, flags, *args, **kwargs)
            target.rename(target.with_name(name + ".kept"))  # Keeps the inode.
            if hook == "fifo":
                os.mkfifo(target)
            elif hook == "socket":
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                    server.bind(str(target))
            elif hook == "symlink_in":
                target.symlink_to("../a.txt")
            elif hook == "symlink_out":
                target.symlink_to("../../out/o.txt")
            else:
                target.mkdir()
        return real_open(path, flags, *args, **kwargs)

    return call
