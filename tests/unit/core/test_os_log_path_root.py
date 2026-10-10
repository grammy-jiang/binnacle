"""OS5: absolute/relative telemetry hash alignment with configured roots."""

import json
from pathlib import Path
from types import SimpleNamespace

from binnacle.mcp.logging_middleware import _args_json
from binnacle.observability.log_safety import (
    path_digest,
    safe_arguments,
    safe_request_payload,
)


def test_custom_root_matches_absolute_and_relative_hash_without_leaking(tmp_path):
    private_root = tmp_path / "super-private-workspace"
    private_root.mkdir()
    target = private_root / "confidential-file.txt"
    target.write_text("nothing sensitive is logged")
    expected = path_digest(str(target))
    assert path_digest("confidential-file.txt", root=private_root) == expected
    sanitized = safe_arguments(
        {"path": "confidential-file.txt", "workdir": "."},
        root=private_root,
    )
    assert sanitized["path"] == f"pathhash:{expected}.file"
    assert str(private_root) not in json.dumps(sanitized)
    assert "confidential-file" not in json.dumps(sanitized)
    message = SimpleNamespace(
        name="read_file", arguments={"path": "confidential-file.txt"}
    )
    payload = safe_request_payload(message, root=private_root)
    assert f"pathhash:{expected}.file" in payload
    assert str(private_root) not in payload
    _, raw = _args_json(message.arguments, root=private_root)
    assert json.loads(raw)["path"] == sanitized["path"]


def test_default_path_hash_semantics_unchanged():
    legacy = Path.home() / "Projects" / "example"
    assert path_digest("example") == path_digest(str(legacy))
    assert path_digest("example", root=Path.home() / "Projects") == path_digest(
        "example"
    )
