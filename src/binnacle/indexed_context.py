"""Production wrapper for explicit ``search_text('@context ...')`` retrieval.

The persistent index implementation is intentionally kept behind this small service
boundary.  The wrapper owns worktree validation, connection caching, freshness
reconciliation, the existing search_text output mapping, and review-grade telemetry.
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastmcp.exceptions import ToolError
from fastmcp.tools.base import ToolResult

from binnacle.callctx import current_call
from binnacle.config import IndexedContextSettings, get_settings
from binnacle.indexed_retrieval import (
    PARSER_VERSION,
    SCHEMA_VERSION,
    PersistentRelationIndex,
)
from binnacle.indexed_surface import PREFIX, to_search_payload

log = logging.getLogger("binnacle.indexed_context")
PILOT_VERSION = "2026-09-19-v1"


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _token(value: Any, limit: int = 200) -> str:
    return "".join(str(value).split())[:limit] or "-"


def _digest(value: str, chars: int = 12) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:chars]


def _log_event(event: str, **fields: Any) -> None:
    try:
        rendered = " ".join(f"{key}={_token(value)}" for key, value in fields.items())
        log.info("event=%s %s", event, rendered)
    except Exception:  # pragma: no cover - telemetry must never break retrieval
        log.debug("event=index_logging_failed", exc_info=True)


def _git_root(path: Path) -> Path:
    directory = path if path.is_dir() else path.parent
    cp = subprocess.run(
        ["git", "-C", str(directory), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
    )
    if cp.returncode != 0 or not cp.stdout.strip():
        raise ToolError(
            "@context requires a path inside a Git worktree. "
            "Set path to the repository root and retry."
        )
    return Path(cp.stdout.strip()).resolve()


@dataclass
class _IndexHandle:
    index: PersistentRelationIndex
    lock: threading.RLock
    db_path: Path


class IndexedContextService:
    """Small LRU of persistent per-worktree indexes for the development pilot."""

    def __init__(self, settings: IndexedContextSettings | None = None) -> None:
        self.settings = settings or get_settings().indexed_context
        self._cache: OrderedDict[Path, _IndexHandle] = OrderedDict()
        self._cache_lock = threading.RLock()

    def _db_path(self, root: Path) -> Path:
        key = _digest(str(root.resolve()), 16)
        return self.settings.index_dir.expanduser().resolve() / f"{key}.db"

    def _get_handle(self, root: Path) -> tuple[_IndexHandle, float, bool]:
        with self._cache_lock:
            handle = self._cache.get(root)
            if handle is not None:
                self._cache.move_to_end(root)
                return handle, 0.0, False

            db_path = self._db_path(root)
            db_existed = db_path.exists()
            t0 = time.perf_counter()
            index = PersistentRelationIndex(root, db_path)
            open_ms = (time.perf_counter() - t0) * 1000.0
            handle = _IndexHandle(index=index, lock=threading.RLock(), db_path=db_path)
            self._cache[root] = handle
            self._cache.move_to_end(root)

            while len(self._cache) > self.settings.max_open_indexes:
                _, evicted = self._cache.popitem(last=False)
                evicted.index.close()

            return handle, open_ms, not db_existed

    def close(self) -> None:
        with self._cache_lock:
            for handle in self._cache.values():
                handle.index.close()
            self._cache.clear()

    def search(self, pattern: str, resolved_path: Path) -> ToolResult:
        if not self.settings.enabled:
            raise ToolError(
                "Indexed @context retrieval is disabled on this Binnacle deployment."
            )
        if not pattern.startswith(PREFIX):
            raise ToolError("Indexed context pattern must start with '@context '.")
        query = pattern[len(PREFIX) :].strip()
        if not query:
            raise ToolError("@context requires a non-empty natural-language query.")

        call_id = current_call.get() or "-"
        phase = "scope"
        root: Path | None = None
        root_hash = "-"
        total_t0 = time.perf_counter()
        try:
            root = _git_root(resolved_path)
            root_hash = _digest(str(root))
            # During the pilot, keep scoping explicit and reviewable.  Supporting
            # subdirectory-scoped semantic retrieval requires a separate ranking
            # contract; silently widening a subdirectory would be misleading.
            if resolved_path.resolve() != root:
                raise ToolError(
                    f"@context path must be the Git worktree root during the pilot: {root}"
                )

            phase = "open"
            handle, open_ms, cold_open = self._get_handle(root)

            with handle.lock:
                phase = "reconcile"
                if self.settings.reconcile_on_query:
                    reconcile = handle.index.update()
                else:
                    reconcile = handle.index.stats(
                        extra={
                            "update_ms": 0.0,
                            "freshness_ms": 0.0,
                            "changed_files": 0,
                            "deleted_files": 0,
                            "hashed_files": 0,
                        }
                    )

                phase = "query"
                query_t0 = time.perf_counter()
                package = handle.index.context_package(
                    query,
                    relation_items=self.settings.relation_items,
                    lexical_items=self.settings.lexical_items,
                    snippet_chars=self.settings.snippet_chars,
                    max_bytes=self.settings.package_max_bytes,
                )
                query_ms = (time.perf_counter() - query_t0) * 1000.0

                phase = "surface"
                surface_t0 = time.perf_counter()
                payload = to_search_payload(root, pattern, package)
                # Match ordinary search_text's absolute-path behavior so a model can
                # pass a returned file directly to read_file.
                for entry in payload.get("entries", []):
                    file_value = entry.get("file")
                    if file_value:
                        entry["file"] = str((root / str(file_value)).resolve())
                surface_ms = (time.perf_counter() - surface_t0) * 1000.0

            payload_text = _compact_json(payload)
            package_bytes = len(payload_text.encode("utf-8"))
            evidence_hashes = ",".join(
                _digest(str(Path(str(entry["file"])).resolve()))
                for entry in payload.get("entries", [])
                if entry.get("file")
            )
            related_items = len(package.get("related_context", []))
            direct_items = len(package.get("direct_matches", []))
            head = str(reconcile.get("head", "unknown"))[:12]
            total_ms = (time.perf_counter() - total_t0) * 1000.0

            _log_event(
                "index_context",
                call=call_id,
                pilot_version=PILOT_VERSION,
                schema_version=SCHEMA_VERSION,
                parser_version=PARSER_VERSION,
                root_hash=root_hash,
                query_hash=_digest(query),
                query_chars=len(query),
                head=head,
                generation=reconcile.get("generation", 0),
                cold_open=str(cold_open).lower(),
                open_ms=f"{open_ms:.2f}",
                reconcile_ms=f"{float(reconcile.get('update_ms', 0.0)):.2f}",
                freshness_ms=f"{float(reconcile.get('freshness_ms', 0.0)):.2f}",
                changed_files=reconcile.get("changed_files", 0),
                deleted_files=reconcile.get("deleted_files", 0),
                hashed_files=reconcile.get("hashed_files", 0),
                query_ms=f"{query_ms:.2f}",
                surface_ms=f"{surface_ms:.2f}",
                total_ms=f"{total_ms:.2f}",
                files=reconcile.get("files", 0),
                nodes=reconcile.get("nodes", 0),
                edges=reconcile.get("edges", 0),
                db_bytes=reconcile.get("db_bytes", 0),
                related_items=related_items,
                direct_items=direct_items,
                package_items=payload.get("count", 0),
                package_bytes=package_bytes,
                package_est_tokens=len(payload_text) // 4,
                evidence_hashes=evidence_hashes or "-",
            )
            return ToolResult(
                content=(
                    f"Returned {payload.get('count', 0)} indexed context items "
                    f"for {query!r}."
                ),
                structured_content=payload,
            )
        except ToolError as exc:
            _log_event(
                "index_context_error",
                call=call_id,
                root_hash=root_hash,
                phase=phase,
                error_class=type(exc).__name__,
                error=str(exc)[:180],
                total_ms=f"{(time.perf_counter() - total_t0) * 1000.0:.2f}",
            )
            raise
        except Exception as exc:
            _log_event(
                "index_context_error",
                call=call_id,
                root_hash=root_hash,
                phase=phase,
                error_class=type(exc).__name__,
                error=str(exc)[:180],
                total_ms=f"{(time.perf_counter() - total_t0) * 1000.0:.2f}",
            )
            raise ToolError(f"Indexed context failed during {phase}: {exc}") from exc


_SERVICE: IndexedContextService | None = None
_SERVICE_LOCK = threading.Lock()


def get_indexed_context_service() -> IndexedContextService:
    global _SERVICE
    with _SERVICE_LOCK:
        if _SERVICE is None:
            _SERVICE = IndexedContextService()
        return _SERVICE
