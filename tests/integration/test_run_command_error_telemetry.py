import asyncio
import re

from fastmcp import Client

from binnacle import server


def _fields(line: str) -> dict[str, str]:
    head = re.split(r" (?:args|error)=", line, maxsplit=1)[0]
    return dict(re.findall(r"(\w+)=(\S+)", head))


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
