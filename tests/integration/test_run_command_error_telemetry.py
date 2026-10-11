import asyncio
import re
import sys

import pytest
from fastmcp import Client

from binnacle import server

LINUX_ONLY = pytest.mark.skipif(
    sys.platform != "linux",
    reason=(
        "Linux durable job engine / background run_command; Darwin counterpart: "
        "tests/platform/darwin/test_native_smoke_mcp.py::test_run_command_sd18; "
        "background jobs are UNAVAILABLE on Darwin by release scope"
    ),
)


def _fields(line: str) -> dict[str, str]:
    head = re.split(r" (?:args|error)=", line, maxsplit=1)[0]
    return dict(re.findall(r"(\w+)=(\S+)", head))


@LINUX_ONLY
def test_workdir_not_directory_is_coded_before_dispatch(tmp_path, caplog):
    path = tmp_path / "file.txt"
    path.write_text("x")

    async def go():
        async with Client(server.mcp) as client:
            return await client.call_tool(
                "run_command",
                {"command": "true", "workdir": str(path)},
                raise_on_error=False,
            )

    with caplog.at_level("INFO"):
        result = asyncio.run(go())

    assert result.is_error is True
    result_line = next(
        record.getMessage()
        for record in caplog.records
        if "event=tool_result" in record.getMessage()
        and "tool=run_command" in record.getMessage()
    )
    fields = _fields(result_line)
    assert fields["error_class"] == "ToolError"
    assert fields["error_code"] == "workdir_not_directory"
    assert not any(
        "event=run_command_dispatch" in record.getMessage() for record in caplog.records
    )
