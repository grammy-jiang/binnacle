"""Optional tokenizer-backed result telemetry.

The tokenizer is deliberately prepared on a daemon thread. tiktoken may need
to populate its encoding cache on first use, and telemetry must never delay or
break an MCP response while that happens.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable
from typing import Any

log = logging.getLogger("binnacle.tokenizer")


def _load_encoding(name: str) -> Any:
    """Import tiktoken lazily and load one named encoding."""
    import tiktoken

    return tiktoken.get_encoding(name)


class TokenCounter:
    """Best-effort token counter for configured client prefixes."""

    def __init__(
        self,
        *,
        enabled: bool,
        encoding: str,
        client_prefixes: tuple[str, ...],
    ) -> None:
        self.enabled = enabled
        self.encoding = encoding
        self.client_prefixes = client_prefixes
        self._encoder: Any | None = None
        self._prepare_started = False
        self._failed = False
        self._count_failure_logged = False
        self._lock = threading.Lock()

    def applies(self, client: str) -> bool:
        return self.enabled and any(
            client.startswith(prefix) for prefix in self.client_prefixes
        )

    def prepare(self) -> None:
        """Start one non-blocking tokenizer load when telemetry is enabled."""
        if not self.enabled:
            return
        with self._lock:
            if self._prepare_started:
                return
            self._prepare_started = True
        threading.Thread(
            target=self._load,
            name="binnacle-tokenizer",
            daemon=True,
        ).start()

    def _load(self) -> None:
        try:
            encoder = _load_encoding(self.encoding)
        except Exception as exc:  # noqa: BLE001 - telemetry must never affect serving
            with self._lock:
                self._failed = True
            log.warning(
                "event=tokenizer_load_failed encoding=%s error_class=%s error=%s",
                self.encoding,
                type(exc).__name__,
                " ".join(str(exc).split())[:200],
            )
            return
        with self._lock:
            self._encoder = encoder
        log.info("event=tokenizer_ready encoding=%s", self.encoding)

    def count(self, parts: Iterable[str]) -> int | None:
        """Count payload text parts, or return None while unavailable."""
        if not self.enabled or self._failed:
            return None
        encoder = self._encoder
        if encoder is None:
            self.prepare()
            return None
        try:
            return sum(len(encoder.encode(part)) for part in parts if part)
        except Exception as exc:  # noqa: BLE001 - telemetry must never affect serving
            if not self._count_failure_logged:
                self._count_failure_logged = True
                log.warning(
                    "event=tokenizer_count_failed encoding=%s error_class=%s error=%s",
                    self.encoding,
                    type(exc).__name__,
                    " ".join(str(exc).split())[:200],
                )
            return None
