"""orjson budget sizing preserves compact UTF-8 result semantics."""

import json

import orjson

from binnacle import search_text_adaptive, search_text_budget


def compact_stdlib(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()


def test_orjson_compact_size_matches_existing_budget_representation():
    payload = {
        "path": "/tmp/中文🙂",
        "pattern": "alpha|βeta",
        "entries": [{"file": "/tmp/a.py", "line": 2, "text": "中文🙂"}],
        "count": 1,
        "truncated": False,
    }
    assert orjson.loads(orjson.dumps(payload)) == payload
    assert len(orjson.dumps(payload)) == len(compact_stdlib(payload))
    assert search_text_budget.structured_bytes(payload) == len(compact_stdlib(payload))
    assert search_text_adaptive.structured_bytes(payload) == len(
        compact_stdlib(payload)
    )
