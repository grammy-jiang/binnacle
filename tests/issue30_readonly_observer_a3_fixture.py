"""Disposable Linux-only A3 sidecar fixture. NEVER a production entrypoint.

Only tests may launch this module and only into a new /tmp/bi30-rpc-*
private directory. The installed Darwin A3 transport is unchanged; its two
native peer/rename calls are shimmed for Linux without changing its HMAC,
generation, endpoint-lock, request sequence or response authenticity logic.
"""

from __future__ import annotations

import os
import signal
import socket
import stat
import struct
import sys
import threading
from pathlib import Path


def _peer(conn: socket.socket) -> tuple[int, int]:
    blob = conn.getsockopt(
        socket.SOL_SOCKET, vars(socket)["SO_PEERCRED"], struct.calcsize("3i")
    )
    pid, uid, _gid = struct.unpack("3i", blob)
    return uid, pid


def _publish(fd: int, source: str, target: str) -> None:
    # Portable fixture-only replacement for Darwin RENAME_EXCL.
    try:
        os.stat(target, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        raise FileExistsError("fixture publication target exists")
    os.rename(source, target, src_dir_fd=fd, dst_dir_fd=fd)
    os.fsync(fd)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2 or sys.platform != "linux" or os.getuid() == 0:
        return 64
    socket_path, root = map(Path, args)
    base = socket_path.parent.parent
    if (
        not base.name.startswith("bi30-rpc-")
        or base.parent != Path("/tmp")
        or socket_path.parent.name != "log-maintenance-observer-ipc"
        or socket_path.name != "observe.sock"
        or root.parent != base
        or root.name != "txn-" + "a" * 32
        or not base.is_absolute()
        or base.resolve() != base
        or not stat.S_ISDIR(base.stat().st_mode)
        or base.stat().st_uid != os.getuid()
        or stat.S_IMODE(base.stat().st_mode) != 0o700
    ):
        return 64

    from binnacle.platform.darwin import generation_runtime, ipc_transport
    from binnacle.platform.darwin import log_maintenance_recovery_rpc as rpc

    ipc_transport._native = lambda: None
    ipc_transport._peer = _peer
    ipc_transport._publish_entry = _publish
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())

    lease = generation_runtime.open_service_lease(
        root=socket_path.parent, label=rpc._LABEL, generation="h" * 32
    )
    rpc.serve_readonly_recovery_over_a3(
        socket_path, lease=lease, transaction_root=root, stop=stop
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
