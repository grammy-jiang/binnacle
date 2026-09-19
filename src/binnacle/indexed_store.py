"""Persistent SQLite storage for indexed repository retrieval."""

from __future__ import annotations

import hashlib
import sqlite3
import subprocess
import time
from pathlib import Path

from binnacle.indexed_parse import (
    DOC_EXT,
    MAX_FILE_BYTES,
    PARSER_VERSION,
    SCHEMA_VERSION,
    IndexStats,
    ParsedFile,
    config_like,
    parse_file,
)


class RelationIndexStore:
    def __init__(self, root: Path, db_path: Path, *, create: bool = True):
        self.root = root.resolve()
        self.db_path = db_path.resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute("PRAGMA temp_store=MEMORY")
        self.db.execute("PRAGMA cache_size=-16000")
        self._ensure_schema()
        if create and self._meta_int("schema_version") != SCHEMA_VERSION:
            self.rebuild()

    def close(self) -> None:
        self.db.close()

    def _ensure_schema(self) -> None:
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        row = self.db.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()
        if row is not None and int(row[0]) != SCHEMA_VERSION:
            self.db.executescript("""
            DROP TABLE IF EXISTS node_fts;
            DROP TABLE IF EXISTS edges;
            DROP TABLE IF EXISTS identifiers;
            DROP TABLE IF EXISTS refs;
            DROP TABLE IF EXISTS definitions;
            DROP TABLE IF EXISTS nodes;
            DROP TABLE IF EXISTS files;
            DELETE FROM meta;
            """)
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS files(
            path TEXT PRIMARY KEY,
            size INTEGER NOT NULL,
            mtime_ns INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            kind TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS nodes(
            node_id TEXT PRIMARY KEY,
            path TEXT NOT NULL,
            kind TEXT NOT NULL,
            symbol TEXT NOT NULL,
            start_line INTEGER NOT NULL,
            end_line INTEGER NOT NULL,
            body TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS nodes_path_idx ON nodes(path);
        CREATE INDEX IF NOT EXISTS nodes_symbol_idx ON nodes(symbol);
        CREATE TABLE IF NOT EXISTS definitions(name TEXT NOT NULL, node_id TEXT NOT NULL, path TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS definitions_name_idx ON definitions(name);
        CREATE INDEX IF NOT EXISTS definitions_path_idx ON definitions(path);
        CREATE TABLE IF NOT EXISTS refs(source_node TEXT NOT NULL, name TEXT NOT NULL, relation TEXT NOT NULL, path TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS refs_name_idx ON refs(name);
        CREATE INDEX IF NOT EXISTS refs_path_idx ON refs(path);
        CREATE TABLE IF NOT EXISTS identifiers(name TEXT NOT NULL, node_id TEXT NOT NULL, path TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS identifiers_name_idx ON identifiers(name);
        CREATE INDEX IF NOT EXISTS identifiers_path_idx ON identifiers(path);
        CREATE TABLE IF NOT EXISTS edges(
            source_node TEXT NOT NULL,
            target_node TEXT NOT NULL,
            relation TEXT NOT NULL,
            ref_name TEXT NOT NULL,
            PRIMARY KEY(source_node,target_node,relation,ref_name)
        );
        CREATE INDEX IF NOT EXISTS edges_source_idx ON edges(source_node,relation);
        CREATE INDEX IF NOT EXISTS edges_target_idx ON edges(target_node,relation);
        CREATE INDEX IF NOT EXISTS edges_ref_name_idx ON edges(ref_name,relation);
        CREATE VIRTUAL TABLE IF NOT EXISTS node_fts USING fts5(
            path, filename, kind, symbol, body,
            content='', contentless_delete=1, tokenize='unicode61'
        );
        """)
        self.db.commit()

    def _meta_int(self, key: str) -> int | None:
        r = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return int(r[0]) if r else None

    def _set_meta(self, **items: object) -> None:
        self.db.executemany(
            "INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            [(k, str(v)) for k, v in items.items()],
        )

    def git_head(self) -> str:
        cp = subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"],
            text=True,
            capture_output=True,
            check=False,
        )
        return cp.stdout.strip() if cp.returncode == 0 else "unknown"

    def tracked_files(self) -> dict[str, tuple[int, int, str]]:
        cp = subprocess.run(
            [
                "git",
                "-C",
                str(self.root),
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
            ],
            capture_output=True,
            check=False,
        )
        rels = (
            cp.stdout.decode("utf-8", "replace").split("\0")
            if cp.returncode == 0
            else []
        )
        out: dict[str, tuple[int, int, str]] = {}
        for rel in rels:
            if not rel:
                continue
            p = self.root / rel
            try:
                st = p.stat()
            except OSError:
                continue
            if not p.is_file() or st.st_size > MAX_FILE_BYTES:
                continue
            kind = self._kind_for(p)
            if not kind:
                continue
            out[rel] = (st.st_size, st.st_mtime_ns, kind)
        return out

    @staticmethod
    def _kind_for(p: Path) -> str | None:
        if p.suffix == ".py":
            return "python"
        if p.suffix.lower() in DOC_EXT:
            return "doc"
        if config_like(p):
            return "config"
        return None

    @staticmethod
    def _hash(raw: bytes) -> str:
        return hashlib.sha256(raw).hexdigest()

    def _read_text(self, rel: str) -> tuple[bytes, str] | None:
        p = self.root / rel
        try:
            raw = p.read_bytes()
        except OSError:
            return None
        if b"\0" in raw:
            return None
        return raw, raw.decode("utf-8", "replace")

    def _clear_all(self) -> None:
        self.db.executescript("""
        DELETE FROM edges; DELETE FROM definitions; DELETE FROM refs; DELETE FROM identifiers;
        DELETE FROM nodes; DELETE FROM files; DELETE FROM node_fts;
        """)

    def rebuild(self) -> IndexStats:
        t0 = time.perf_counter()
        files = self.tracked_files()
        with self.db:
            self._clear_all()
            for rel, (size, mtime_ns, kind) in files.items():
                data = self._read_text(rel)
                if data is None:
                    continue
                raw, text = data
                self._replace_file(
                    rel,
                    size,
                    mtime_ns,
                    kind,
                    self._hash(raw),
                    parse_file(rel, self.root / rel, text),
                )
            self._resolve_edges_full()
            self._set_meta(
                schema_version=SCHEMA_VERSION,
                parser_version=PARSER_VERSION,
                root=self.root,
                head=self.git_head(),
                indexed_at=time.time(),
                generation=(self._meta_int("generation") or 0) + 1,
            )
        return self.stats(extra={"build_ms": (time.perf_counter() - t0) * 1000})

    def _delete_file(self, rel: str) -> None:
        node_rows = list(
            self.db.execute("SELECT rowid,node_id FROM nodes WHERE path=?", (rel,))
        )
        node_ids = [r["node_id"] for r in node_rows]
        if node_ids:
            q = ",".join("?" for _ in node_ids)
            self.db.execute(
                f"DELETE FROM edges WHERE source_node IN ({q}) OR target_node IN ({q})",  # nosec
                node_ids + node_ids,
            )
            rowids = [r["rowid"] for r in node_rows]
            qr = ",".join("?" for _ in rowids)
            self.db.execute(f"DELETE FROM node_fts WHERE rowid IN ({qr})", rowids)  # nosec
        self.db.execute("DELETE FROM definitions WHERE path=?", (rel,))
        self.db.execute("DELETE FROM refs WHERE path=?", (rel,))
        self.db.execute("DELETE FROM identifiers WHERE path=?", (rel,))
        self.db.execute("DELETE FROM nodes WHERE path=?", (rel,))
        self.db.execute("DELETE FROM files WHERE path=?", (rel,))

    def _replace_file(
        self,
        rel: str,
        size: int,
        mtime_ns: int,
        kind: str,
        sha256: str,
        parsed: ParsedFile,
    ) -> None:
        self._delete_file(rel)
        self.db.execute(
            "INSERT INTO files(path,size,mtime_ns,sha256,kind) VALUES(?,?,?,?,?)",
            (rel, size, mtime_ns, sha256, kind),
        )
        if parsed.nodes:
            self.db.executemany(
                "INSERT INTO nodes(node_id,path,kind,symbol,start_line,end_line,body) VALUES(?,?,?,?,?,?,?)",
                [
                    (
                        n.node_id,
                        n.path,
                        n.kind,
                        n.symbol,
                        n.start_line,
                        n.end_line,
                        n.body,
                    )
                    for n in parsed.nodes
                ],
            )
            rowids = {
                r["node_id"]: r["rowid"]
                for r in self.db.execute(
                    "SELECT rowid,node_id FROM nodes WHERE path=?", (rel,)
                )
            }
            self.db.executemany(
                "INSERT INTO node_fts(rowid,path,filename,kind,symbol,body) VALUES(?,?,?,?,?,?)",
                [
                    (
                        rowids[n.node_id],
                        n.path,
                        Path(n.path).name,
                        n.kind,
                        n.symbol,
                        n.body,
                    )
                    for n in parsed.nodes
                ],
            )
            defs = [
                (n.symbol, n.node_id, n.path)
                for n in parsed.nodes
                if n.kind in {"function", "class"}
            ]
            if defs:
                self.db.executemany(
                    "INSERT INTO definitions(name,node_id,path) VALUES(?,?,?)", defs
                )
        if parsed.refs:
            self.db.executemany(
                "INSERT INTO refs(source_node,name,relation,path) VALUES(?,?,?,?)",
                [(x.source_node, x.name, x.relation, rel) for x in parsed.refs],
            )
        if parsed.identifiers:
            self.db.executemany(
                "INSERT INTO identifiers(name,node_id,path) VALUES(?,?,?)",
                [(x.name, x.node_id, rel) for x in parsed.identifiers],
            )

    def _resolve_edges_full(self) -> None:
        self.db.execute("DELETE FROM edges")
        # Unique definitions only for call/doc references.
        self.db.execute("""
        INSERT OR IGNORE INTO edges(source_node,target_node,relation,ref_name)
        SELECT r.source_node, MIN(d.node_id), r.relation, r.name
        FROM refs r JOIN definitions d ON d.name=r.name
        WHERE r.relation IN ('call','doc_ref')
        GROUP BY r.source_node, r.name, r.relation
        HAVING COUNT(DISTINCT d.node_id)=1
        """)
        # Config consumers are identifier-based; suppress very broad keys.
        self.db.execute("""
        INSERT OR IGNORE INTO edges(source_node,target_node,relation,ref_name)
        SELECT r.source_node, i.node_id, 'config_consumer', r.name
        FROM refs r JOIN identifiers i ON i.name=r.name
        WHERE r.relation='config_consumer'
          AND (SELECT COUNT(DISTINCT i2.node_id) FROM identifiers i2 WHERE i2.name=r.name) BETWEEN 1 AND 30
        """)

    def _names_for_paths(self, paths: list[str]) -> tuple[set[str], set[str]]:
        if not paths:
            return set(), set()
        q = ",".join("?" for _ in paths)
        call_names = {
            r[0]
            for r in self.db.execute(
                f"SELECT name FROM definitions WHERE path IN ({q})",  # nosec
                paths,
            )
        }
        call_names.update(
            r[0]
            for r in self.db.execute(
                f"SELECT name FROM refs WHERE relation IN ('call','doc_ref') AND path IN ({q})",  # nosec
                paths,
            )
        )
        ident_names = {
            r[0]
            for r in self.db.execute(
                f"SELECT name FROM identifiers WHERE path IN ({q})",  # nosec
                paths,
            )
        }
        ident_names.update(
            r[0]
            for r in self.db.execute(
                f"SELECT name FROM refs WHERE relation='config_consumer' AND path IN ({q})",  # nosec
                paths,
            )
        )
        return call_names, ident_names

    def _resolve_edges_incremental(
        self, call_names: set[str], ident_names: set[str]
    ) -> None:
        self.db.execute(
            "CREATE TEMP TABLE IF NOT EXISTS affected_call_names(name TEXT PRIMARY KEY)"
        )
        self.db.execute(
            "CREATE TEMP TABLE IF NOT EXISTS affected_ident_names(name TEXT PRIMARY KEY)"
        )
        self.db.execute("DELETE FROM affected_call_names")
        self.db.execute("DELETE FROM affected_ident_names")
        if call_names:
            self.db.executemany(
                "INSERT OR IGNORE INTO affected_call_names(name) VALUES(?)",
                [(x,) for x in call_names],
            )
            self.db.execute("""
            DELETE FROM edges
            WHERE relation IN ('call','doc_ref')
              AND ref_name IN (SELECT name FROM affected_call_names)
            """)
            self.db.execute("""
            INSERT OR IGNORE INTO edges(source_node,target_node,relation,ref_name)
            SELECT r.source_node, MIN(d.node_id), r.relation, r.name
            FROM refs r
            JOIN affected_call_names a ON a.name=r.name
            JOIN definitions d ON d.name=r.name
            WHERE r.relation IN ('call','doc_ref')
            GROUP BY r.source_node, r.name, r.relation
            HAVING COUNT(DISTINCT d.node_id)=1
            """)
        if ident_names:
            self.db.executemany(
                "INSERT OR IGNORE INTO affected_ident_names(name) VALUES(?)",
                [(x,) for x in ident_names],
            )
            self.db.execute("""
            DELETE FROM edges
            WHERE relation='config_consumer'
              AND ref_name IN (SELECT name FROM affected_ident_names)
            """)
            self.db.execute("""
            INSERT OR IGNORE INTO edges(source_node,target_node,relation,ref_name)
            SELECT r.source_node, i.node_id, 'config_consumer', r.name
            FROM refs r
            JOIN affected_ident_names a ON a.name=r.name
            JOIN identifiers i ON i.name=r.name
            WHERE r.relation='config_consumer'
              AND (SELECT COUNT(DISTINCT i2.node_id) FROM identifiers i2 WHERE i2.name=r.name) BETWEEN 1 AND 30
            """)

    def stats(self, extra: IndexStats | None = None) -> IndexStats:
        head_row = self.db.execute("SELECT value FROM meta WHERE key='head'").fetchone()
        out: IndexStats = {
            "files": self.db.execute("SELECT COUNT(*) FROM files").fetchone()[0],
            "nodes": self.db.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
            "edges": self.db.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
            "db_bytes": self.db_path.stat().st_size if self.db_path.exists() else 0,
            "generation": self._meta_int("generation") or 0,
            "head": str(head_row[0]) if head_row else "unknown",
        }
        if extra:
            out.update(extra)
        return out
