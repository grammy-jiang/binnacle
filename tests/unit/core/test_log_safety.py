"""Regression tests for privacy-preserving MCP journal serialization."""

import json
from types import SimpleNamespace

from binnacle.mcp.logging_middleware import _args_json, _scalar
from binnacle.observability.log_safety import (
    REDACTED,
    path_digest,
    safe_arguments,
    safe_client_name,
    safe_path,
    safe_request_payload,
    safe_tool_name,
    safe_turn_id,
)
from binnacle.observability.logstats_parse import _path_hash


def test_untrusted_argument_values_and_keys_cannot_enter_journal(tmp_path):
    secret = "SYNTHETIC_PRIVATE_VALUE_20261009"
    path = str(tmp_path / (secret + ".py"))
    original = {
        "path": path,
        "command": "printf " + secret,
        "stdin": secret,
        "content": secret,
        "pattern": secret,
        "glob": "*" + secret,
        "job_id": secret,
        "cursor": secret,
        "start_line": 8,
        "wait_seconds": 41,
        secret: {"deep": secret},
    }
    sanitized = safe_arguments(original)
    assert secret not in json.dumps(sanitized)
    assert path not in json.dumps(sanitized)
    assert sanitized["command"] == sanitized["stdin"] == REDACTED
    assert sanitized["start_line"] == 8
    assert sanitized["wait_seconds"] == 41
    assert sanitized["unknown_keys"] == 1
    assert sanitized["path"].startswith("pathhash:")
    assert _path_hash(sanitized["path"]) == _path_hash(path)
    unredacted_chars, record = _args_json(original)
    assert unredacted_chars > len(record)
    assert secret not in record
    assert json.loads(record)["start_line"] == 8


def test_paths_keep_analytics_join_identity_without_actual_path(tmp_path):
    file = str(tmp_path / "some-private-name.config")
    folder = str(tmp_path / "some-private-directory")
    assert safe_path(file).endswith(".file")
    assert not safe_path(folder).endswith(".file")
    assert _path_hash(safe_path(file)) == path_digest(file)
    assert _path_hash(safe_path(folder)) == path_digest(folder)
    assert file not in safe_path(file)


def test_known_job_ids_and_cursor_markers_preserved():
    assert safe_arguments({"job_id": "0123456789ab", "cursor": "start"}) == {
        "job_id": "0123456789ab",
        "cursor": "start",
    }
    assert safe_arguments({"job_id": "very-sensitive", "cursor": "secret"}) == {
        "job_id": REDACTED,
        "cursor": REDACTED,
    }


def test_request_serializer_cannot_emit_arbitrary_metadata():
    secret = "SYNTHETIC_PRIVATE_VALUE_20261009"
    direct = SimpleNamespace(
        name="write_file", arguments={"path": "/tmp/" + secret, "content": secret}
    )
    params = SimpleNamespace(name="run_command", arguments={"command": secret})
    indirect = SimpleNamespace(name=None, params=params)
    unknown = SimpleNamespace(
        name=None,
        params=SimpleNamespace(clientInfo={"name": secret}, access_token=secret),
    )
    for message in [direct, indirect, unknown]:
        encoded = safe_request_payload(message)
        assert secret not in encoded
        assert json.loads(encoded)
    assert '"write_file"' in safe_request_payload(direct)
    assert '"run_command"' in safe_request_payload(indirect)


def test_client_tool_and_header_identifiers_are_constrained():
    secret = "SYNTHETIC_PRIVATE_VALUE_20261009"
    assert safe_client_name("claude-code") == "claude-code"
    assert safe_client_name("openai-mcp(ChatGPT)") == "openai-mcp(ChatGPT)"
    assert secret not in safe_client_name("untrusted-" + secret)
    assert safe_tool_name("run_command") == "run_command"
    assert safe_tool_name("not-a-tool-" + secret) == "unknown_tool"
    assert safe_turn_id("wfr_0123abcd/9zq1") == "wfr_0123abcd/9zq1"
    assert safe_turn_id("turn-a/call-1") == "turn-a/call-1"
    assert secret not in safe_turn_id(secret)


def test_lifted_result_strings_are_allowlisted():
    secret = "SYNTHETIC_PRIVATE_VALUE_20261009"
    assert _scalar("exact", "match") == "exact"
    assert _scalar("text", "kind") == "text"
    assert _scalar("0123456789ab", "job_id") == "0123456789ab"
    assert _scalar(secret, "match") == REDACTED
    assert _scalar(secret, "mime_guess") == REDACTED
    assert _scalar(secret, "job_id") == REDACTED


def test_malformed_arguments_fail_closed_without_raw_serializer_fallback():
    from collections.abc import Mapping

    class BrokenMapping(Mapping):
        def __iter__(self):
            raise RuntimeError("do not invoke raw fallback")

        def __len__(self):
            return 1

        def __getitem__(self, key):
            raise RuntimeError("do not invoke raw fallback")

    message = SimpleNamespace(name="write_file", arguments=BrokenMapping())
    assert safe_request_payload(message) == '{"type":"unavailable"}'


def test_missing_client_unknown_arguments_and_relative_paths_are_safe():
    assert safe_client_name(None) == "-"
    assert safe_tool_name(None) == "unknown_tool"
    assert safe_arguments(None) == {}
    assert safe_arguments(["malformed", "input"]) == {}
    assert safe_arguments({"glob": "", "path": 42}) == {
        "glob": "",
        "path": REDACTED,
    }
    assert path_digest("relative-file.py") == _path_hash("relative-file.py")


def test_unresolvable_path_is_redacted_without_breaking_tools(monkeypatch):
    from pathlib import Path

    def fail_resolve(self):
        raise OSError("synthetic private path was not resolvable")

    monkeypatch.setattr(Path, "resolve", fail_resolve)
    assert safe_path("/tmp/not-resolvable") == REDACTED


def test_probe_marker_is_instrumentation_only_and_validated():
    from binnacle.observability.log_safety import (
        SMOKE_CORRELATION_FIELD,
        safe_smoke_proof,
    )

    valid = "a" * 32
    assert safe_smoke_proof({SMOKE_CORRELATION_FIELD: valid}) == valid
    for metadata in (
        None,
        {},
        [],
        "not-a-mapping",
        {SMOKE_CORRELATION_FIELD: "untrusted-secret"},
        {SMOKE_CORRELATION_FIELD: "B" * 32},
        {SMOKE_CORRELATION_FIELD: 123},
        {SMOKE_CORRELATION_FIELD: valid + "\ncredential=bad"},
    ):
        assert safe_smoke_proof(metadata) is None
