"""MCP registration wrapper for the search_text implementation."""

from collections.abc import Callable
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.tools.base import ToolResult
from pydantic import Field

SearchImpl = Callable[
    [str, str, str | None, bool, int | None, bool, int, bool], ToolResult
]


def register_search_text(
    mcp: FastMCP,
    impl: SearchImpl,
    *,
    output_schema: dict,
    max_results_default: int,
    max_results_cap: int,
) -> None:
    @mcp.tool(
        annotations={"readOnlyHint": True, "openWorldHint": False},
        output_schema=output_schema,
    )
    def search_text(
        pattern: Annotated[
            str,
            Field(
                description=(
                    "Regex (Rust syntax), or `@context <query>` for indexed repository "
                    "discovery when path is the Git worktree root. Use fixed_strings for literal text."
                )
            ),
        ],
        path: Annotated[
            str,
            Field(
                description="File or directory to search. Absolute (~ ok); relative resolves against ~/Projects."
            ),
        ] = "~/Projects",
        glob: Annotated[
            str | None,
            Field(description="Only search files matching this glob (e.g. *.py)."),
        ] = None,
        fixed_strings: Annotated[
            bool, Field(description="Treat pattern as literal text.")
        ] = False,
        context_lines: Annotated[
            int | None,
            Field(
                ge=0,
                le=100,
                description="Context lines around each match. Omit for automatic context on few matches.",
            ),
        ] = None,
        names_only: Annotated[
            bool, Field(description="Return only files and their match counts.")
        ] = False,
        max_results: Annotated[
            int,
            Field(ge=1, le=max_results_cap, description="Cap on returned matches."),
        ] = max_results_default,
        line_numbers: Annotated[
            bool,
            Field(
                description="Prefix each context line with its line number (grep -n style)."
            ),
        ] = False,
    ) -> ToolResult:
        """Search repository content. Normal regex search replaces grep -rn;
        names_only replaces grep -c; line_numbers supplies grep -n style context.
        Prefer this over grep in run_command. When the implementation location is
        unknown, use ``@context <query>`` with ``path`` set to the Git worktree
        root, then verify/narrow with exact search as needed.
        """
        return impl(
            pattern,
            path,
            glob,
            fixed_strings,
            context_lines,
            names_only,
            max_results,
            line_numbers,
        )
