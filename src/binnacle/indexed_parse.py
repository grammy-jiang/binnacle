from __future__ import annotations

import ast
import re
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
