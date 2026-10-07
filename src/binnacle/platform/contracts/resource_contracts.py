"""Optional resource accounting, independent of process execution and history."""

from typing import Protocol


class ResourceAccounting(Protocol):
    """Best-effort counters and opaque identities; no process ownership."""

    def prepare(self, *, log_ready: bool = False) -> str | None: ...

    def create(self, job_id: str) -> str | None: ...

    def wrap_argv(self, argv: list[str], identity: str | None) -> list[str]:
        """Decorate supplied argv without mutation; no identity returns it as is."""
        ...

    def snapshot(self, identity: str | None) -> dict[str, object]: ...

    def wait_empty(self, identity: str) -> bool:
        """Wait for an empty scope, or return False if that cannot be established."""
        ...

    def cleanup(self, identity: str | None) -> bool:
        """Return True only for no identity, an absent scope, or completed removal."""
        ...


class NoResourceAccounting:
    """Explicit no-op accounting that cannot clean up unknown legacy identities."""

    __slots__ = ()

    def prepare(self, *, log_ready: bool = False) -> str | None:
        return None

    def create(self, job_id: str) -> str | None:
        return None

    def wrap_argv(self, argv: list[str], identity: str | None) -> list[str]:
        return argv

    def snapshot(self, identity: str | None) -> dict[str, object]:
        return {}

    def wait_empty(self, identity: str) -> bool:
        return False

    def cleanup(self, identity: str | None) -> bool:
        return identity is None
