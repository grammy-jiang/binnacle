"""Query ranking and bounded context packaging."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable

from binnacle.indexed_parse import (
    BACKTICK,
    STRUCTURAL_STOP,
    ContextItem,
    ContextPackage,
    query_terms,
)
from binnacle.indexed_store import RelationIndexStore


class RelationIndexQueryMixin(RelationIndexStore):
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
