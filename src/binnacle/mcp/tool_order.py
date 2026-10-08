"""Preserve Binnacle's public listing order across native mounted providers."""

from collections.abc import Sequence

from fastmcp.server.transforms import Transform
from fastmcp.tools.base import Tool

_RANK = {
    name: index
    for index, name in enumerate(
        (
            "read_file",
            "list_files",
            "search_text",
            "edit_file",
            "write_file",
            "run_command",
            "job_status",
            "stop_job",
        )
    )
}


class PublicToolOrder(Transform):
    """Order known names; retain every object and unknown names' relative order."""

    async def list_tools(self, tools: Sequence[Tool]) -> Sequence[Tool]:
        return sorted(tools, key=lambda tool: _RANK.get(tool.name, len(_RANK)))
