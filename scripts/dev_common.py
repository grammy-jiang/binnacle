"""Shared types for the repository development helper."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from pathlib import Path


@dataclasses.dataclass(frozen=True)
class CommandResult:
    returncode: int
    output: str


Runner = Callable[[Sequence[str], Path], CommandResult]
Which = Callable[[str], str | None]
