"""MCP output schema for search_text.

Kept outside the 500-line implementation module so telemetry can evolve without
forcing search-algorithm refactors.
"""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "pattern": {"type": "string"},
        "entries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file": {"type": "string"},
                    "line": {"type": "integer"},
                    "text": {"type": "string"},
                    "context_first_line": {"type": "integer"},
                    "context": {"type": "string"},
                    "count": {"type": "integer"},
                },
                "required": ["file"],
            },
        },
        "count": {"type": "integer"},
        "truncated": {"type": "boolean"},
        "note": {"type": "string"},
    },
    "required": ["path", "pattern", "count", "truncated"],
}
