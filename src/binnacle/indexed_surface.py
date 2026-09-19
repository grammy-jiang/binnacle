from __future__ import annotations

from pathlib import Path

from binnacle.indexed_retrieval import ContextPackage

PREFIX = "@context "


def to_search_payload(
    root: Path, pattern: str, package: ContextPackage, *, direct_first: bool = False
) -> dict:
    entries = []
    lanes = (
        [("direct", "direct_matches"), ("related", "related_context")]
        if direct_first
        else [("related", "related_context"), ("direct", "direct_matches")]
    )
    for lane, key in lanes:
        items = (
            package.get("direct_matches", [])
            if key == "direct_matches"
            else package.get("related_context", [])
        )
        for item in items:
            reason = item.get("reason", "")
            label = f"[{lane}] {item.get('symbol', '')} ({item.get('kind', '')})"
            if reason and reason not in {lane, "related", "direct"}:
                label += f" — {reason}"
            lines = item.get("lines") or [1, 1]
            entries.append(
                {
                    "file": item["path"],
                    "line": int(lines[0]),
                    "text": label,
                    "context_first_line": int(lines[0]),
                    "context": item.get("excerpt", ""),
                }
            )
    return {
        "path": str(root),
        "pattern": pattern,
        "entries": entries,
        "count": len(entries),
        "truncated": True,
        "note": (
            "Indexed context package. [direct] entries are lexical candidates; [related] entries are supporting relation evidence and are not proof of the answer. Verify ambiguity with regex."
            if direct_first
            else "Indexed context package. [related] entries include retrieval provenance; inspect them before broad regex, then use exact search to verify/narrow. Entries are not regex match counts."
        ),
    }
