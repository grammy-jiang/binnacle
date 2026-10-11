"""Focused Search server using the existing MCP adapter."""

from fastmcp import FastMCP

from binnacle.config import RootsSettings, SearchTextSettings, get_settings
from binnacle.features.files.paths import FileToolAccess, focused_file_access
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
        file_access = focused_file_access(roots)
    search = FastMCP("binnacle-search", on_duplicate="error")
    search_text.register(
        search,
        file_access=file_access,
        roots=roots,
        settings=search_settings,
        rg_bin=rg_bin,
    )
    return search
