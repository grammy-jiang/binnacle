"""Optional historical resource output, independent of collection/storage."""

from typing import Protocol


class SystemResourceHistory(Protocol):
    def render_window(self, since: str, until: str | None) -> str: ...
