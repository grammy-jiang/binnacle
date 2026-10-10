"""Linux systemd readiness notification, isolated from the durable Job Manager."""

import os
import socket
from collections.abc import Callable


def notify_ready(on_error: Callable[[], None]) -> None:
    """Notify when the manager is accepting requests; never terminate owned jobs."""
    target = os.environ.get("NOTIFY_SOCKET")
    if not target:
        return
    address = "\0" + target[1:] if target.startswith("@") else target
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as notifier:
            notifier.connect(address)
            notifier.sendall(b"READY=1\nSTATUS=Binnacle job manager ready")
    except OSError:
        on_error()
