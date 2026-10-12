"""A no-follow directory chain from '/' kept as a stack (r6 W2 X3c-a3, SD-78).

search_text and list_files glob check paths that rg reported by path
string. Each directory component from '/' is opened no-follow relative to
its opened parent (fd_walk.TRAVERSE_FLAGS, O_PATH on Linux). Only the
chain of the current path is open: when the next path is checked, every
descriptor that is not a prefix of its directory is closed first. Peak
descriptors are therefore the path depth plus one (RX3c-F1: a per-call
cache of every directory exhausted RLIMIT_NOFILE). rg emits the files of
one directory together, so most of the reuse remains.
"""

import os
from types import TracebackType

from binnacle.features.files import fd_walk
from binnacle.platform.contracts.special_file_contracts import (
    TOO_MANY_OPEN_FILES_ERRNOS,
)

# A descriptor shortage is not evidence that a path failed the walk.
EXHAUSTED = TOO_MANY_OPEN_FILES_ERRNOS


class DirectoryChain:
    """The opened directory chain of the current path; close() or 'with'."""

    def __init__(self) -> None:
        self._parts: list[str] = []
        self._fds: list[int] = []  # _fds[0] is '/', _fds[i + 1] is _parts[i]

    def __enter__(self) -> "DirectoryChain":  # noqa: PYI034 - Python 3.10
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._truncate(0)
        if self._fds:
            os.close(self._fds.pop())

    def _truncate(self, keep: int) -> None:
        """Keep '/' and the first keep components open; close the rest."""
        while len(self._fds) > keep + 1:
            os.close(self._fds.pop())
            self._parts.pop()

    def directory(self, parts: tuple[str, ...]) -> int:
        """The descriptor of /parts; every component is opened no-follow.

        An EMFILE or ENFILE closes this chain and retries once, so the
        descriptors of this call never cause it; a second shortage raises.
        """
        try:
            return self._descend(parts)
        except OSError as exc:
            if exc.errno not in EXHAUSTED:
                raise
            self.close()
            return self._descend(parts)

    def _descend(self, parts: tuple[str, ...]) -> int:
        keep = 0
        limit = min(len(parts), len(self._parts))
        while keep < limit and self._parts[keep] == parts[keep]:
            keep += 1
        self._truncate(keep)
        if not self._fds:
            self._fds.append(os.open("/", fd_walk.TRAVERSE_FLAGS))
        for name in parts[len(self._parts) :]:
            fd = os.open(name, fd_walk.TRAVERSE_FLAGS, dir_fd=self._fds[-1])
            self._fds.append(fd)
            self._parts.append(name)
        return self._fds[-1]
