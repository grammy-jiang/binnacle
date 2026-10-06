"""Linux journald implementation of the service-log contract."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass

from binnacle.service_log_contracts import ServiceLogError


def _services(value: str | Sequence[str]) -> tuple[str, ...]:
    return (value,) if isinstance(value, str) else tuple(value)


@dataclass(frozen=True, slots=True)
class JournalServiceLogSource:
    """Read user-unit logs with the current journalctl behavior."""

    command_timeout_s: float | None = None

    def _run(self, argv: list[str]) -> str:
        try:
            if self.command_timeout_s is None:
                proc = subprocess.run(
                    argv,
                    capture_output=True,
                    text=True,
                    check=False,
                )
            else:
                proc = subprocess.run(
                    argv,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=self.command_timeout_s,
                )
        except subprocess.TimeoutExpired as exc:
            timeout = self.command_timeout_s
            shown = f"{timeout:g} s" if timeout is not None else "the configured limit"
            raise ServiceLogError(f"journalctl timed out after {shown}") from exc
        except OSError as exc:
            raise ServiceLogError(
                f"journalctl failed to start: {str(exc)[:200]}"
            ) from exc
        if proc.returncode != 0:
            detail = proc.stderr.strip()[:200]
            raise ServiceLogError(
                "journalctl failed" + (f": {detail}" if detail else "")
            )
        return proc.stdout

    def read_spec(
        self,
        services: str | Sequence[str],
        since: str,
        until: str | None = None,
    ) -> str:
        """Linux-only compatibility path for journalctl time specifications."""

        argv = ["journalctl", "--user"]
        for name in _services(services):
            argv += ["-u", name]
        # Preserve logstats_io's literal option order.
        argv += ["--since", since, "-o", "cat", "--no-pager"]
        if until:
            argv += ["--until", until]
        return self._run(argv)

    def read_window(
        self,
        services: Sequence[str],
        since_epoch: float,
        until_epoch: float | None = None,
    ) -> str:
        """Semantic epoch window with deploy_smoke's exact Linux conversion."""

        argv = ["journalctl", "--user"]
        for name in services:
            argv += ["-u", name]
        argv += ["--since", f"@{int(since_epoch)}"]
        if until_epoch is not None:
            argv += ["--until", f"@{int(until_epoch) + 1}"]
        # Preserve deploy_smoke's literal option order.
        argv += ["--no-pager", "-o", "cat"]
        return self._run(argv)
