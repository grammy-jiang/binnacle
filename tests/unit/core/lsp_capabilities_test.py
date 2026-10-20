"""P1.2 typed cases against the fake fixture only."""

from dataclasses import dataclass
from typing import Any

import pytest

from tests.fixtures.lsp.lsp_peer import LspPeer

SPAN = {"start": {"line": 1, "character": 4}, "end": {"line": 1, "character": 10}}
LOCATION = {"uri": "file:///fixture.py", "range": SPAN}
OTHER = {"uri": "file:///other.py", "range": SPAN}


@dataclass(frozen=True)
class SemanticCase:
    method: str
    capability: str
    expected: Any
    definition: str = "location"


CASES = [
    SemanticCase("textDocument/definition", "definitionProvider", LOCATION),
    SemanticCase("textDocument/definition", "definitionProvider", None, "null"),
    SemanticCase(
        "textDocument/definition", "definitionProvider", [LOCATION, OTHER], "multiple"
    ),
    SemanticCase(
        "textDocument/definition",
        "definitionProvider",
        [
            {
                "targetUri": "file:///fixture.py",
                "targetRange": SPAN,
                "targetSelectionRange": SPAN,
            }
        ],
        "link",
    ),
    SemanticCase("textDocument/references", "referencesProvider", [LOCATION, OTHER]),
    SemanticCase(
        "textDocument/documentSymbol",
        "documentSymbolProvider",
        [
            {
                "name": "sample",
                "kind": 12,
                "range": SPAN,
                "selectionRange": SPAN,
                "children": [],
            }
        ],
    ),
    SemanticCase(
        "workspace/symbol",
        "workspaceSymbolProvider",
        [{"name": "sample", "kind": 12, "location": LOCATION}],
    ),
    SemanticCase(
        "textDocument/hover",
        "hoverProvider",
        {"contents": {"kind": "markdown", "value": "**sample** → 文"}, "range": SPAN},
    ),
]


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"{c.method}-{c.definition}")
def test_lsp_semantic_payload(case: SemanticCase):
    with LspPeer("--definition", case.definition) as peer:
        capabilities = peer.request("initialize")["result"]["capabilities"]
        assert capabilities[case.capability] is True
        for request_id in (2, 3):
            assert peer.request(case.method, request_id)["result"] == case.expected
        peer.finish()


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"{c.method}-{c.definition}")
def test_lsp_disabled_capability(case: SemanticCase):
    with LspPeer("--disable", case.method) as peer:
        capabilities = peer.request("initialize")["result"]["capabilities"]
        assert capabilities[case.capability] is False
        assert sum(value is True for value in capabilities.values()) == 4
        assert peer.request(case.method, 2)["error"] == {
            "code": -32601,
            "message": "Method not found",
        }
        peer.finish()
