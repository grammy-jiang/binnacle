"""Shared synchronization for watchdog decide-and-act sections."""

import threading

ACT_LOCK = threading.Lock()
