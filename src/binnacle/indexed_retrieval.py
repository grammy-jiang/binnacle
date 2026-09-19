from __future__ import annotations

import ast
import hashlib
import json
import re
import sqlite3
import subprocess
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

SCHEMA_VERSION = 3
PARSER_VERSION = 1
MAX_FILE_BYTES = 1_000_000
MAX_NODE_BODY = 50_000
DOC_EXT = {".md", ".markdown", ".rst", ".txt"}
CONFIG_EXT = {".toml", ".ini", ".cfg", ".yaml", ".yml"}
CONFIG_TAGS = ("config", "default", "setting", "profile", "policy", "manifest")
CONFIG_SKIP = {"pyproject.toml", "tox.ini", ".pre-commit-config.yaml"}
BACKTICK = re.compile(r"`([A-Za-z_][A-Za-z0-9_.:-]*)`")


class IndexStats(TypedDict, total=False):
    files: int
    nodes: int
    edges: int
    db_bytes: int
    generation: int
    head: str
    build_ms: float
    update_ms: float
    freshness_ms: float
    changed_files: int
    deleted_files: int
    hashed_files: int


class FreshnessDetails(TypedDict):
    changed: list[str]
    deleted: list[str]
    metadata_only: list[tuple[str, int, int, str, str]]
    hashes: int
    scan_ms: float
    head: str
    current: dict[str, tuple[int, int, str]]


class FreshnessReport(TypedDict):
    changed: list[str]
    deleted: list[str]
    metadata_only: list[tuple[str, int, int, str, str]]
    hashes: int
    scan_ms: float
    head: str


class ContextItem(TypedDict):
    path: str
    symbol: str
    kind: str
    lines: list[int]
    reason: str
    excerpt: str


class ContextPackage(TypedDict, total=False):
    query: str
    direct_matches: list[ContextItem]
    related_context: list[ContextItem]
    item_count: int
    structured_bytes: int


STRUCTURAL_STOP = {
    "find",
    "locate",
    "implementation",
    "implementations",
    "responsible",
    "code",
    "runtime",
    "behind",
    "documented",
    "behavior",
    "starting",
    "start",
    "follow",
    "unique",
    "cross",
    "file",
    "direct",
    "call",
    "chain",
    "exactly",
    "hops",
    "hop",
    "which",
    "reached",
    "second",
    "downstream",
    "ultimately",
    "handles",
    "setting",
    "controlling",
    "consumes",
    "similarly",
    "named",
    "one",
    "among",
}

QUERY_STOP = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
    "this",
    "that",
    "these",
    "those",
    "current",
}


def query_terms(pattern: str) -> list[str]:
    """Turn a natural-language/context pattern into stable FTS terms."""
    text = pattern.replace("(?i)", " ").replace("\\b", " ").replace("|", " ")
    values = re.findall(r"[A-Za-z0-9_][A-Za-z0-9_.:-]*|[\u4e00-\u9fff]{2,}", text)
    out: list[str] = []
    for value in values:
        value = value.strip(".:-").lower()
        if (
            len(value) < 2
            or value in QUERY_STOP
            or (value.isdigit() and len(value) == 1)
        ):
            continue
        if value not in out:
            out.append(value)
    return out[:32]


@dataclass(frozen=True)
class ParsedNode:
    node_id: str
    path: str
    kind: str
    symbol: str
    start_line: int
    end_line: int
    body: str


@dataclass(frozen=True)
class ParsedRef:
    source_node: str
    name: str
    relation: str


@dataclass(frozen=True)
class ParsedIdentifier:
    node_id: str
    name: str


@dataclass
class ParsedFile:
    nodes: list[ParsedNode]
    refs: list[ParsedRef]
    identifiers: list[ParsedIdentifier]


class OnePassPythonExtractor(ast.NodeVisitor):
    def __init__(self, rel: str, text: str):
        self.rel = rel
        self.text = text
        self.lines = text.splitlines(keepends=True)
        self.nodes: list[ParsedNode] = []
        self.refs: list[ParsedRef] = []
        self.identifiers: list[ParsedIdentifier] = []
        self.current_node: list[str] = []
        self.module_id = f"py-module:{rel}"

    def source(self, node: ast.AST) -> str:
        start = getattr(node, "lineno", 1)
        end = getattr(node, "end_lineno", start) or start
        return "".join(self.lines[start - 1 : end])[:MAX_NODE_BODY]

    def add_ident(self, name: str) -> None:
        if not name:
            return
        node = self.current_node[-1] if self.current_node else self.module_id
        self.identifiers.append(ParsedIdentifier(node, name))

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_callable(node, "function")

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_callable(node, "function")

    def _visit_callable(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, kind: str
    ) -> None:
        nid = f"py-symbol:{self.rel}:{node.lineno}:{node.name}"
        end = node.end_lineno or node.lineno
        self.nodes.append(
            ParsedNode(
                nid, self.rel, kind, node.name, node.lineno, end, self.source(node)
            )
        )
        self.current_node.append(nid)
        # Decorators/defaults belong to this symbol too.
        for child in node.decorator_list:
            self.visit(child)
        for child in node.args.defaults:
            self.visit(child)
        for kw_default in node.args.kw_defaults:
            if kw_default is not None:
                self.visit(kw_default)
        if node.returns:
            self.visit(node.returns)
        for stmt in node.body:
            self.visit(stmt)
        self.current_node.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        nid = f"py-symbol:{self.rel}:{node.lineno}:{node.name}"
        end = node.end_lineno or node.lineno
        self.nodes.append(
            ParsedNode(
                nid, self.rel, "class", node.name, node.lineno, end, self.source(node)
            )
        )
        self.current_node.append(nid)
        for base in node.bases:
            self.visit(base)
        for kw in node.keywords:
            self.visit(kw.value)
        for child in node.decorator_list:
            self.visit(child)
        for stmt in node.body:
            self.visit(stmt)
        self.current_node.pop()

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and self.current_node:
            self.refs.append(ParsedRef(self.current_node[-1], node.func.id, "call"))
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        self.add_ident(node.id)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self.add_ident(node.attr)
        self.generic_visit(node)


def _module_body(tree: ast.Module, lines: list[str]) -> str:
    parts: list[str] = []
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if not hasattr(n, "lineno"):
            continue
        start = n.lineno
        end = getattr(n, "end_lineno", start) or start
        parts.extend(lines[start - 1 : end])
    return "".join(parts)[:30_000]


def parse_python(rel: str, text: str) -> ParsedFile:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return ParsedFile([], [], [])
    ex = OnePassPythonExtractor(rel, text)
    lines = text.splitlines(keepends=True)
    ex.nodes.append(
        ParsedNode(
            ex.module_id,
            rel,
            "python_module",
            Path(rel).stem,
            1,
            len(lines),
            _module_body(tree, lines),
        )
    )
    ex.visit(tree)
    # De-duplicate identifiers/refs generated by repeated AST appearances.
    return ParsedFile(
        ex.nodes, list(dict.fromkeys(ex.refs)), list(dict.fromkeys(ex.identifiers))
    )


def parse_markdown(rel: str, text: str) -> ParsedFile:
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if re.match(r"^#{1,6}\s+", line)] or [0]
    nodes: list[ParsedNode] = []
    refs: list[ParsedRef] = []
    for j, start in enumerate(starts):
        end = starts[j + 1] if j + 1 < len(starts) else len(lines)
        body = "".join(lines[start:end])[:MAX_NODE_BODY]
        title = (
            lines[start].lstrip("#").strip()
            if lines and start < len(lines)
            else "document"
        )[:180]
        nid = f"doc:{rel}:{start + 1}"
        nodes.append(
            ParsedNode(
                nid, rel, "doc_section", title, start + 1, max(start + 1, end), body
            )
        )
        for ref in BACKTICK.findall(body):
            refs.append(ParsedRef(nid, ref.split(".")[-1], "doc_ref"))
    return ParsedFile(nodes, list(dict.fromkeys(refs)), [])


def config_like(path: Path) -> bool:
    lname = path.name.lower()
    return (
        path.suffix.lower() in CONFIG_EXT
        and lname not in CONFIG_SKIP
        and any(tag in lname for tag in CONFIG_TAGS)
    )


def parse_config(rel: str, text: str) -> ParsedFile:
    section = ""
    nodes: list[ParsedNode] = []
    refs: list[ParsedRef] = []
    for i, line in enumerate(text.splitlines(), 1):
        if len(nodes) >= 500:
            break
        msec = re.match(r"\s*\[+([^\]]+)\]+\s*$", line)
        if msec:
            section = msec.group(1)
            continue
        m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_.-]{2,})\s*[:=]\s*(.*)$", line)
        if not m:
            continue
        key, val = m.groups()
        nid = f"cfg:{rel}:{i}:{key}"
        nodes.append(
            ParsedNode(
                nid,
                rel,
                "config_key",
                key,
                i,
                i,
                f"{section} {key} {val}"[:MAX_NODE_BODY],
            )
        )
        norm = key.replace("-", "_").replace(".", "_")
        tail = re.split(r"[.-]", key)[-1].replace("-", "_")
        refs.append(ParsedRef(nid, norm, "config_consumer"))
        if tail != norm:
            refs.append(ParsedRef(nid, tail, "config_consumer"))
    return ParsedFile(nodes, list(dict.fromkeys(refs)), [])


def parse_file(rel: str, path: Path, text: str) -> ParsedFile:
    if path.suffix == ".py":
        return parse_python(rel, text)
    if path.suffix.lower() in DOC_EXT:
        return parse_markdown(rel, text)
    if config_like(path):
        return parse_config(rel, text)
    return ParsedFile([], [], [])


class PersistentRelationIndex:
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

    @staticmethod
    def terms(q: str) -> list[str]:
        return [x for x in query_terms(q) if x.lower() not in STRUCTURAL_STOP][:32]

    def lexical_nodes(self, q: str, limit: int = 180) -> list[str]:
        ts = self.terms(q)
        if not ts:
            return []
        match = " OR ".join('"' + x.replace('"', '""') + '"' for x in ts)
        rowids = [
            r[0]
            for r in self.db.execute(
                "SELECT rowid FROM node_fts WHERE node_fts MATCH ? ORDER BY bm25(node_fts,2.0,4.0,0.3,8.0,1.0) LIMIT ?",
                (match, limit),
            )
        ]
        if not rowids:
            return []
        qmarks = ",".join("?" for _ in rowids)
        mapping = {
            r["rowid"]: r["node_id"]
            for r in self.db.execute(
                f"SELECT rowid,node_id FROM nodes WHERE rowid IN ({qmarks})",  # nosec
                rowids,
            )
        }
        return [mapping[x] for x in rowids if x in mapping]

    def _node_meta(self, ids: Iterable[str]) -> dict[str, sqlite3.Row]:
        ids = list(dict.fromkeys(ids))
        if not ids:
            return {}
        q = ",".join("?" for _ in ids)
        return {
            r["node_id"]: r
            for r in self.db.execute(
                f"SELECT node_id,path,kind,symbol,start_line,end_line,body FROM nodes WHERE node_id IN ({q})",  # nosec
                ids,
            )
        }

    def retrieve_evidence(self, q: str, k: int = 20) -> list[dict[str, object]]:
        ranked = self.lexical_nodes(q, 180)
        score: dict[str, float] = {}
        provenance: dict[str, tuple[str, str | None, str | None, int | None]] = {}
        provenance_strength: dict[str, float] = {}

        def add(
            nid: str,
            value: float,
            why: tuple[str, str | None, str | None, int | None],
        ) -> None:
            score[nid] = score.get(nid, 0.0) + value
            if value > provenance_strength.get(nid, -1.0):
                provenance_strength[nid] = value
                provenance[nid] = why

        for i, nid in enumerate(ranked, 1):
            add(nid, 1 / (60 + i), ("lexical", None, None, i))
        low = q.lower()
        doc_intent = "documented" in low or "documentation" in low
        cfg_intent = "setting" in low or "configuration" in low or "config" in low
        downstream = "downstream" in low or "ultimately" in low
        seeds = ranked[:24]
        seed_rank = {nid: i for i, nid in enumerate(seeds, 1)}
        if seeds:
            qs = ",".join("?" for _ in seeds)
            for row in self.db.execute(
                f"SELECT source_node,target_node,relation FROM edges WHERE source_node IN ({qs})",  # nosec
                seeds,
            ):
                i = seed_rank[row["source_node"]]
                w = {
                    "doc_ref": 1.5 if doc_intent else 0.7,
                    "config_consumer": 1.5 if cfg_intent else 0.7,
                    "call": 0.75 if downstream else 0.35,
                }.get(row["relation"], 0.2)
                add(
                    row["target_node"],
                    w / (60 + i),
                    ("outgoing", row["source_node"], row["relation"], 1),
                )
            for row in self.db.execute(
                f"SELECT source_node,target_node,relation FROM edges WHERE target_node IN ({qs})",  # nosec
                seeds,
            ):
                i = seed_rank[row["target_node"]]
                w = {"doc_ref": 0.25, "config_consumer": 0.2, "call": 0.18}.get(
                    row["relation"], 0.1
                )
                add(
                    row["source_node"],
                    w / (60 + i),
                    ("incoming", row["target_node"], row["relation"], 1),
                )
        explicit = BACKTICK.findall(q)
        if explicit and (
            "two hop" in low
            or "two hops" in low
            or "second hop" in low
            or "exactly two" in low
        ):
            seed_name = explicit[0].split(".")[-1]
            defs = [
                r[0]
                for r in self.db.execute(
                    "SELECT node_id FROM definitions WHERE name=?", (seed_name,)
                )
            ]
            if len(defs) == 1:
                frontier = defs
                add(defs[0], 2.0, ("entry", None, None, 0))
                for depth in (1, 2):
                    if not frontier:
                        break
                    qs = ",".join("?" for _ in frontier)
                    pairs = list(
                        self.db.execute(
                            f"SELECT source_node,target_node FROM edges WHERE relation='call' AND source_node IN ({qs})",  # nosec
                            frontier,
                        )
                    )
                    next_frontier: list[str] = []
                    for row in pairs:
                        target = row["target_node"]
                        if target not in next_frontier:
                            next_frontier.append(target)
                        add(
                            target,
                            4.0 if depth == 1 else 12.0,
                            ("hop", row["source_node"], "call", depth),
                        )
                    frontier = next_frontier

        # Fetch all scored nodes once. Relation provenance always points at a seed
        # or another scored node, so the same metadata map can render explanations.
        metas = self._node_meta(score)
        fscore: dict[str, float] = {}
        best_node: dict[str, str] = {}
        best_node_score: dict[str, float] = {}
        for nid, node_score in score.items():
            m = metas.get(nid)
            if not m:
                continue
            path = m["path"]
            # Preserve the existing file-ranking arithmetic exactly.
            fscore[path] = max(fscore.get(path, 0.0), node_score) + 0.08 * node_score
            if node_score > best_node_score.get(path, -1.0):
                best_node_score[path] = node_score
                best_node[path] = nid

        def label(nid: str | None) -> str:
            if not nid:
                return ""
            m = metas.get(nid)
            if not m:
                return nid
            return f"{m['path']}:{m['symbol']}"

        def reason(nid: str) -> str:
            kind, other, relation, depth = provenance.get(
                nid, ("ranked", None, None, None)
            )
            if kind == "lexical":
                return f"lexical rank {depth}"
            if kind == "outgoing":
                return f"{relation} from {label(other)}"
            if kind == "incoming":
                return f"source with {relation} to {label(other)}"
            if kind == "entry":
                return "explicit entry symbol"
            if kind == "hop":
                return f"call hop {depth} from {label(other)}"
            return kind

        ordered = sorted(fscore, key=lambda path: fscore[path], reverse=True)[:k]
        return [
            {
                "path": path,
                "node_id": best_node[path],
                "score": fscore[path],
                "reason": reason(best_node[path]),
            }
            for path in ordered
        ]

    def retrieve_files(self, q: str, k: int = 20) -> list[str]:
        return [str(x["path"]) for x in self.retrieve_evidence(q, k)]

    def context_package(
        self,
        q: str,
        relation_items: int = 8,
        lexical_items: int = 2,
        snippet_chars: int = 700,
        max_bytes: int = 8_500,
    ) -> ContextPackage:
        evidence = self.retrieve_evidence(q, max(relation_items, 20))
        related_evidence = evidence[:relation_items]
        related = [str(x["path"]) for x in related_evidence]
        evidence_by_path = {str(x["path"]): x for x in related_evidence}
        lexical_nodes = self.lexical_nodes(q, 180)
        metas = self._node_meta(
            list(lexical_nodes) + [str(x["node_id"]) for x in related_evidence]
        )
        best_by_path: dict[str, sqlite3.Row] = {}
        lexical_paths: list[str] = []
        for nid in lexical_nodes:
            m = metas.get(nid)
            if not m:
                continue
            path = m["path"]
            if path not in best_by_path:
                best_by_path[path] = m
                lexical_paths.append(path)
        direct = [path for path in lexical_paths if path not in related][:lexical_items]

        def item(path: str, lane: str) -> ContextItem | None:
            evidence_item = evidence_by_path.get(path) if lane == "related" else None
            if evidence_item is not None:
                row = metas.get(str(evidence_item["node_id"]))
            else:
                row = best_by_path.get(path)
            if row is None:
                row = self.db.execute(
                    "SELECT node_id,path,kind,symbol,start_line,end_line,body FROM nodes WHERE path=? ORDER BY start_line LIMIT 1",
                    (path,),
                ).fetchone()
            if row is None:
                return None
            if evidence_item is not None:
                explanation = str(evidence_item["reason"])
            else:
                explanation = "direct lexical match"
            body = " ".join(row["body"].split())[:snippet_chars]
            return {
                "path": row["path"],
                "symbol": row["symbol"],
                "kind": row["kind"],
                "lines": [row["start_line"], row["end_line"]],
                "reason": explanation,
                "excerpt": body,
            }

        rel_items = [x for path in related if (x := item(path, "related"))]
        direct_items = [x for path in direct if (x := item(path, "direct"))]
        package: ContextPackage = {
            "query": q,
            "direct_matches": direct_items,
            "related_context": rel_items,
            "item_count": len(direct_items) + len(rel_items),
        }
        # Keep the model-facing package bounded independently of repository/query
        # size. Trim excerpts first; only drop tail items if metadata alone would
        # otherwise exceed the budget. Exact tokenizer measurements are done by the
        # benchmark, while runtime enforcement stays dependency-free and UTF-8 based.
        min_excerpt = 160

        def size() -> int:
            return len(
                json.dumps(package, ensure_ascii=False, separators=(",", ":")).encode(
                    "utf-8"
                )
            )

        items = package["related_context"] + package["direct_matches"]
        while size() > max_bytes:
            candidates = [x for x in items if len(x.get("excerpt", "")) > min_excerpt]
            if candidates:
                x = max(candidates, key=lambda y: len(y.get("excerpt", "")))
                text = x.get("excerpt", "")
                x["excerpt"] = text[: max(min_excerpt, len(text) - 120)]
                continue
            # Preserve relation evidence preferentially; direct tail is cheapest to
            # remove, then related tail if necessary.
            if package["direct_matches"]:
                package["direct_matches"].pop()
                items = package["related_context"] + package["direct_matches"]
                continue
            if package["related_context"]:
                package["related_context"].pop()
                items = package["related_context"]
                continue
            break
        package["item_count"] = len(package["direct_matches"]) + len(
            package["related_context"]
        )
        package["structured_bytes"] = size()
        return package
