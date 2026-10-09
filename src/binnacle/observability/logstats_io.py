"""Linux compatibility IO for usage statistics."""

from collections.abc import Sequence


def fetch_journal(
    unit: str | Sequence[str], since: str, until: str | None = None
) -> str:
    """Preserve the existing journalctl-style CLI time grammar on Linux."""

    from binnacle.platform.linux.service_journal import JournalServiceLogSource

    return JournalServiceLogSource(command_timeout_s=None).read_spec(unit, since, until)
