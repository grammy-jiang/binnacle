"""Freshness detection and incremental index updates."""

from __future__ import annotations

import time
from collections.abc import Iterable
from pathlib import Path

from binnacle.indexed_parse import (
    MAX_FILE_BYTES,
    FreshnessDetails,
    FreshnessReport,
    IndexStats,
    parse_file,
)
from binnacle.indexed_store import RelationIndexStore


class RelationIndexRefreshMixin(RelationIndexStore):
    def _freshness_details(self) -> FreshnessDetails:
        t0 = time.perf_counter()
        current = self.tracked_files()
        old = {
            r["path"]: r
            for r in self.db.execute("SELECT path,size,mtime_ns,sha256,kind FROM files")
        }
        deleted = sorted(set(old) - set(current))
        candidates = [
            rel
            for rel, (size, mtime, kind) in current.items()
            if rel not in old
            or old[rel]["size"] != size
            or old[rel]["mtime_ns"] != mtime
            or old[rel]["kind"] != kind
        ]
        changed: list[str] = []
        unchanged_metadata_changed: list[tuple[str, int, int, str, str]] = []
        hashes = 0
        for rel in candidates:
            data = self._read_text(rel)
            if data is None:
                continue
            raw, _ = data
            h = self._hash(raw)
            hashes += 1
            if (
                rel not in old
                or old[rel]["sha256"] != h
                or old[rel]["kind"] != current[rel][2]
            ):
                changed.append(rel)
            else:
                unchanged_metadata_changed.append(
                    (rel, current[rel][0], current[rel][1], current[rel][2], h)
                )
        return {
            "changed": changed,
            "deleted": deleted,
            "metadata_only": unchanged_metadata_changed,
            "hashes": hashes,
            "scan_ms": (time.perf_counter() - t0) * 1000,
            "head": self.git_head(),
            "current": current,
        }

    def freshness(self) -> FreshnessReport:
        details = self._freshness_details()
        return {
            "changed": details["changed"],
            "deleted": details["deleted"],
            "metadata_only": details["metadata_only"],
            "hashes": details["hashes"],
            "scan_ms": details["scan_ms"],
            "head": details["head"],
        }

    def _apply_update(
        self,
        *,
        changed: list[str],
        deleted: list[str],
        metadata_only: list[tuple[str, int, int, str, str]],
        current: dict[str, tuple[int, int, str]],
        head: str,
    ) -> None:
        affected_paths = list(dict.fromkeys(deleted + changed))
        old_call_names, old_ident_names = self._names_for_paths(affected_paths)
        with self.db:
            for rel in deleted:
                self._delete_file(rel)
            for rel in changed:
                if rel not in current:
                    continue
                data = self._read_text(rel)
                if data is None:
                    continue
                raw, text = data
                size, mtime, kind = current[rel]
                self._replace_file(
                    rel,
                    size,
                    mtime,
                    kind,
                    self._hash(raw),
                    parse_file(rel, self.root / rel, text),
                )
            for rel, size, mtime, kind, h in metadata_only:
                self.db.execute(
                    "UPDATE files SET size=?,mtime_ns=?,kind=?,sha256=? WHERE path=?",
                    (size, mtime, kind, h, rel),
                )
            if affected_paths:
                new_call_names, new_ident_names = self._names_for_paths(affected_paths)
                self._resolve_edges_incremental(
                    old_call_names | new_call_names, old_ident_names | new_ident_names
                )
                self._set_meta(generation=(self._meta_int("generation") or 0) + 1)
            self._set_meta(head=head, indexed_at=time.time())

    def update(self) -> IndexStats:
        t0 = time.perf_counter()
        fresh = self._freshness_details()
        current = fresh["current"]
        changed = list(fresh["changed"])
        deleted = list(fresh["deleted"])
        self._apply_update(
            changed=changed,
            deleted=deleted,
            metadata_only=list(fresh["metadata_only"]),
            current=current,
            head=str(fresh["head"]),
        )
        return self.stats(
            extra={
                "update_ms": (time.perf_counter() - t0) * 1000,
                "freshness_ms": fresh["scan_ms"],
                "changed_files": len(changed),
                "deleted_files": len(deleted),
                "hashed_files": fresh["hashes"],
            }
        )

    def update_paths(self, paths: Iterable[str | Path]) -> IndexStats:
        """Fast path for paths already identified by a filesystem watcher."""
        t0 = time.perf_counter()
        old = {
            r["path"]: r
            for r in self.db.execute("SELECT path,size,mtime_ns,sha256,kind FROM files")
        }
        changed: list[str] = []
        deleted: list[str] = []
        metadata_only: list[tuple[str, int, int, str, str]] = []
        current: dict[str, tuple[int, int, str]] = {}
        hashes = 0
        for item in paths:
            p = Path(item)
            if p.is_absolute():
                try:
                    rel = str(p.resolve().relative_to(self.root))
                except ValueError:
                    continue
            else:
                rel = str(p)
                p = self.root / rel
            try:
                st = p.stat()
            except OSError:
                if rel in old:
                    deleted.append(rel)
                continue
            kind = self._kind_for(p)
            if not p.is_file() or st.st_size > MAX_FILE_BYTES or not kind:
                if rel in old:
                    deleted.append(rel)
                continue
            current[rel] = (st.st_size, st.st_mtime_ns, kind)
            data = self._read_text(rel)
            if data is None:
                if rel in old:
                    deleted.append(rel)
                continue
            raw, _ = data
            h = self._hash(raw)
            hashes += 1
            if rel not in old or old[rel]["sha256"] != h or old[rel]["kind"] != kind:
                changed.append(rel)
            else:
                metadata_only.append((rel, st.st_size, st.st_mtime_ns, kind, h))
        self._apply_update(
            changed=changed,
            deleted=deleted,
            metadata_only=metadata_only,
            current=current,
            head=self.git_head(),
        )
        return self.stats(
            extra={
                "update_ms": (time.perf_counter() - t0) * 1000,
                "freshness_ms": 0.0,
                "changed_files": len(changed),
                "deleted_files": len(deleted),
                "hashed_files": hashes,
            }
        )
