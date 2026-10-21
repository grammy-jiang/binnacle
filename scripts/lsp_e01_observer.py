"""Read-only and ambiguity-aware observer-to-tunnel request group joins.

No hashes or base IDs escape the host-local caller's in-memory analysis.
"""

from __future__ import annotations

import collections
import sqlite3
from pathlib import Path


def _observer(
    db_path: Path | None,
) -> tuple[dict[tuple[str, str], str], set[tuple[str, str]]]:
    if db_path is None or not db_path.is_file():
        return {}, set()
    # Read-only SQLite URI and query-only mode; never write WAL/config tables.
    uri = db_path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    base_for_hash: dict[str, str] = {}
    conflicted: set[str] = set()
    try:
        conn.execute("PRAGMA query_only=ON")
        for h, b in conn.execute(
            "SELECT request_hash,base_hash FROM tunnel_events "
            "WHERE request_hash IS NOT NULL AND base_hash IS NOT NULL"
        ):
            if not isinstance(h, str) or not isinstance(b, str) or not h or not b:
                continue
            old = base_for_hash.setdefault(h, b)
            if old != b:
                conflicted.add(h)
        seen: dict[tuple[str, str], set[str | None]] = collections.defaultdict(set)
        for gen, call, request_hash in conn.execute(
            "SELECT gen,call,request_hash FROM calls"
        ):
            key = (str(gen), str(call))
            h = request_hash if isinstance(request_hash, str) and request_hash else None
            seen[key].add(h)
        mapping: dict[tuple[str, str], str] = {}
        ambiguity: set[tuple[str, str]] = set()
        for key, hashes in seen.items():
            # A second unresolved request hash is never evidence of a
            # successful exact base join, even when another row resolves.
            if len(hashes) != 1 or None in hashes:
                ambiguity.add(key)
                continue
            h = next(iter(hashes))
            if h in conflicted:
                ambiguity.add(key)
                continue
            if h in base_for_hash:
                mapping[key] = base_for_hash[h]
        return mapping, ambiguity
    finally:
        conn.close()
