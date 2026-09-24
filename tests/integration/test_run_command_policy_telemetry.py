import asyncio
import re

import mcp.types
from fastmcp import Client

from binnacle import jobs, server
from binnacle.config import RunCommandSettings
from binnacle.run_command_telemetry import auto_background_policy_hash
from binnacle.tools import run_command as rc
from binnacle.tools import stop_job as sj


def _fields(line: str) -> dict[str, str]:
    head = re.split(r" (?:args|error)=", line, maxsplit=1)[0]
    return dict(re.findall(r"(\w+)=(\S+)", head))


def _run(name: str, args: dict, client_info):
    async def go():
        async with Client(server.mcp, client_info=client_info) as client:
            return await client.call_tool(name, args, raise_on_error=False)

    return asyncio.run(go())


def test_auto_background_marker_hashes_policy_and_rule_without_pattern(
    monkeypatch, caplog
):
    info = mcp.types.Implementation(name="openai-mcp-test", version="1")
    pattern = r"SECRET_RULE_SHOULD_NOT_BE_LOGGED"
    settings = RunCommandSettings(auto_background_patterns={"openai-mcp": (pattern,)})
    monkeypatch.setattr(rc, "RUN_SETTINGS", settings)
    monkeypatch.setattr(jobs, "WARMUP_S", 0.05)

    with caplog.at_level("INFO", logger="binnacle.run_command"):
        result = _run(
            "run_command",
            {"command": f"{pattern}; sleep 2", "workdir": "/tmp"},
            info,
        )

    marker_line = next(
        record.getMessage()
        for record in caplog.records
        if "event=run_command_auto_background" in record.getMessage()
    )
    marker = _fields(marker_line)
    assert re.fullmatch(r"[0-9a-f]{12}", marker["policy_hash"])
    assert re.fullmatch(r"[0-9a-f]{12}", marker["rule_hash"])
    assert pattern not in marker_line
    assert marker["policy_hash"] == auto_background_policy_hash(
        settings.auto_background_patterns
    )

    payload = result.structured_content
    assert payload is not None and payload["state"] == "running"
    sj.stop_job_impl(payload["job_id"])


def test_run_command_tool_config_fingerprints_effective_policy(caplog):
    settings = server.get_settings().run_command
    expected_rules = sum(
        len(patterns) for patterns in settings.auto_background_patterns.values()
    )

    with caplog.at_level("INFO", logger="binnacle.server"):
        server.log_effective_config()

    line = next(
        record.getMessage()
        for record in caplog.records
        if "event=tool_config tool=run_command" in record.getMessage()
    )
    fields = _fields(line)
    assert fields["auto_background_clients"] == str(
        len(settings.auto_background_patterns)
    )
    assert fields["auto_background_rules"] == str(expected_rules)
    assert fields["auto_background_policy_hash"] == auto_background_policy_hash(
        settings.auto_background_patterns
    )
