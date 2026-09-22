"""Shared result telemetry lifts only low-cardinality scalar facts."""

import json

from fastmcp.tools.base import ToolResult

from binnacle import logging_middleware


def test_result_fields_lift_low_cardinality_tool_facts_only():
    secret = "do-not-copy-content"
    result = ToolResult(
        content="summary",
        structured_content={
            "content": secret,
            "snippet": secret,
            "path": "/tmp/secret",
            "fits_in_one_call": True,
            "lossy": False,
            "next_start_line": 31,
            "mime_guess": "text/plain",
            "mode": "glob",
            "match": "exact",
            "first_change_line": 7,
            "previous_bytes": 10,
            "runtime_s": 1.25,
            "last_output_age_s": 0.5,
        },
    )
    fields = logging_middleware._result_fields(result)
    assert fields["fits_in_one_call"] == "true"
    assert fields["lossy"] == "false"
    assert fields["next_start_line"] == "31"
    assert fields["mime_guess"] == "text/plain"
    assert fields["mode"] == "glob" and fields["match"] == "exact"
    assert fields["first_change_line"] == "7"
    assert fields["previous_bytes"] == "10"
    assert fields["runtime_s"] == "1.25"
    assert fields["last_output_age_s"] == "0.5"
    serialized = json.dumps(fields)
    assert secret not in serialized and "/tmp/secret" not in serialized
