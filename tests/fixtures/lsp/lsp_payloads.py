"""Deterministic semantic payloads; no provider or filesystem access."""

from typing import Any

CAPABILITIES = {
    "textDocument/definition": "definitionProvider",
    "textDocument/references": "referencesProvider",
    "textDocument/documentSymbol": "documentSymbolProvider",
    "workspace/symbol": "workspaceSymbolProvider",
    "textDocument/hover": "hoverProvider",
}


def semantic_result(method: str, definition: str) -> Any:
    span = {
        "start": {"line": 1, "character": 4},
        "end": {"line": 1, "character": 10},
    }
    location = {"uri": "file:///fixture.py", "range": span}
    if method == "textDocument/definition":
        return {
            "location": location,
            "link": [
                {
                    "targetUri": location["uri"],
                    "targetRange": span,
                    "targetSelectionRange": span,
                }
            ],
            "null": None,
            "multiple": [location, {"uri": "file:///other.py", "range": span}],
        }[definition]
    if method == "textDocument/references":
        return [location, {"uri": "file:///other.py", "range": span}]
    if method == "textDocument/documentSymbol":
        return [
            {
                "name": "sample",
                "kind": 12,
                "range": span,
                "selectionRange": span,
                "children": [],
            }
        ]
    if method == "workspace/symbol":
        return [{"name": "sample", "kind": 12, "location": location}]
    if method == "textDocument/hover":
        return {
            "contents": {"kind": "markdown", "value": "**sample** → 文"},
            "range": span,
        }
    raise ValueError(method)
