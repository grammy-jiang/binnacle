"""Shared, redacted service stdout/stderr forwarding for a supplied writer.

The platform composition root owns host selection and writer construction.
This module only consumes an already-authorized writer and never imports
Darwin or Linux adapters.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Iterator
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from threading import RLock
from typing import Protocol


class ServiceWriter(Protocol):
    def start(self) -> None: ...

    def write(self, text: str) -> None: ...

    def sync(self) -> None: ...

    def close(self) -> None: ...


@contextmanager
def redirect_private_output(writer: ServiceWriter) -> Iterator[None]:
    """Do not write partial records that could split sensitive values."""
    lock = RLock()

    class Output(io.TextIOBase):
        def __init__(self):
            self.pending = ""
            self.overflow = False

        def write(self, text):
            with lock:
                for piece in text.splitlines(keepends=True):
                    self.pending += piece
                    if len(self.pending) > 65536:
                        self.pending, self.overflow = "", True
                    if piece.endswith("\n"):
                        writer.write(
                            "[oversized record omitted]"
                            if self.overflow
                            else self.pending
                        )
                        self.pending, self.overflow = "", False
            return len(text)

        def flush(self):
            # Do not persist fragments: a credential may span separate writes.
            with lock:
                writer.sync()

    writer.start()
    output = Output()
    logger = logging.getLogger()
    old_handlers = logger.handlers[:]
    handler = logging.StreamHandler(output)
    logger.handlers = [handler]
    try:
        with redirect_stdout(output), redirect_stderr(output):
            yield
    finally:
        logger.handlers = old_handlers
        with lock:
            if output.pending or output.overflow:
                writer.write("[unterminated record omitted]")
            writer.close()
