from pathlib import Path

from binnacle.indexed_surface import to_search_payload


def test_related_lane_precedes_direct_and_preserves_provenance():
    package = {
        "related_context": [
            {
                "path": "src/related.py",
                "symbol": "helper",
                "kind": "function",
                "reason": "called by target",
                "lines": [12, 18],
                "excerpt": "def helper(): ...",
            }
        ],
        "direct_matches": [
            {
                "path": "src/direct.py",
                "symbol": "target",
                "kind": "function",
                "reason": "direct",
                "lines": [30, 40],
                "excerpt": "def target(): ...",
            }
        ],
    }

    payload = to_search_payload(Path("/repo"), "@context target", package)

    assert [entry["file"] for entry in payload["entries"]] == [
        "src/related.py",
        "src/direct.py",
    ]
    assert payload["entries"][0]["text"] == (
        "[related] helper (function) — called by target"
    )
    assert payload["entries"][1]["text"] == "[direct] target (function)"
    assert payload["entries"][0]["line"] == 12
    assert payload["entries"][0]["context_first_line"] == 12
    assert payload["entries"][0]["context"] == "def helper(): ..."
    assert payload["count"] == 2
    assert payload["truncated"] is True
    assert payload["path"] == "/repo"
    assert "retrieval provenance" in payload["note"]


def test_direct_first_changes_lane_order_and_note():
    package = {
        "related_context": [
            {"path": "related.py", "symbol": "r", "kind": "module", "lines": [2, 2]}
        ],
        "direct_matches": [
            {"path": "direct.py", "symbol": "d", "kind": "module", "lines": [3, 3]}
        ],
    }

    payload = to_search_payload(
        Path("/repo"), "@context item", package, direct_first=True
    )

    assert [entry["file"] for entry in payload["entries"]] == [
        "direct.py",
        "related.py",
    ]
    assert "[direct] entries are lexical candidates" in payload["note"]


def test_missing_optional_fields_use_safe_defaults():
    package = {
        "related_context": [{"path": "minimal.py"}],
        "direct_matches": [],
    }

    payload = to_search_payload(Path("."), "query", package)

    assert payload["count"] == 1
    assert payload["entries"][0] == {
        "file": "minimal.py",
        "line": 1,
        "text": "[related]  ()",
        "context_first_line": 1,
        "context": "",
    }


def test_empty_package_returns_empty_search_shape():
    payload = to_search_payload(Path("/repo"), "query", {})

    assert payload["entries"] == []
    assert payload["count"] == 0
    assert payload["truncated"] is True
