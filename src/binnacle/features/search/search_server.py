"""Focused Search server using the existing MCP adapter."""

from fastmcp import FastMCP
from fastmcp.server.transforms.tool_transform import ToolTransform
from fastmcp.tools.tool_transform import ToolTransformConfig

from binnacle.config import RootsSettings, SearchTextSettings, get_settings
from binnacle.features.files.paths import FileToolAccess
from binnacle.features.search.tools import search_text


def create_search_server(
    *,
    roots: RootsSettings | None = None,
    file_access: FileToolAccess | None = None,
    search_settings: SearchTextSettings | None = None,
    rg_bin: str | None = None,
) -> FastMCP:
    """Build an independent Search child for native FastMCP composition."""
    if roots is None or search_settings is None or rg_bin is None:
        defaults = get_settings()
        roots = defaults.roots if roots is None else roots
        search_settings = (
            defaults.search_text if search_settings is None else search_settings
        )
        rg_bin = defaults.rg_bin if rg_bin is None else rg_bin
    if file_access is None:
        from binnacle.platform.composition import native_file_capability

        capability = native_file_capability()
        if capability is not None:
            file_access = FileToolAccess(
                roots=roots,
                files=None,
                search=None,
                generation="unavailable",
                capability=capability,
            )
    search = FastMCP("binnacle-search", on_duplicate="error")
    search_text.register(
        search,
        file_access=file_access,
        roots=roots,
        settings=search_settings,
        rg_bin=rg_bin,
    )
    if file_access is not None:
        search.add_transform(
            ToolTransform(
                {
                    "search_text": ToolTransformConfig(
                        description=(
                            "Search repository content. Normal regex search replaces grep -rn; "
                            "names_only replaces grep -c; line_numbers supplies grep -n style context. "
                            "Prefer this over grep in run_command. "
                            "Darwin per-file size limit: 16 MiB (16,777,216 bytes), "
                            "further bounded by the remaining aggregate 16 MiB input budget. "
                            "Larger files are skipped whole; the summary reports the reason "
                            "and results are marked truncated."
                        )
                    )
                }
            )
        )
    return search
