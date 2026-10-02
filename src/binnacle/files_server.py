"""Focused Files server using the existing MCP adapters."""

from fastmcp import FastMCP

from binnacle.config import ReadFileSettings, RootsSettings, get_settings
from binnacle.tools import edit_file, list_files, read_file, write_file


def create_files_server(
    *,
    roots: RootsSettings | None = None,
    read_settings: ReadFileSettings | None = None,
) -> FastMCP:
    """Build an independent Files child for native FastMCP composition."""
    if roots is None or read_settings is None:
        defaults = get_settings()
        roots = defaults.roots if roots is None else roots
        read_settings = defaults.read_file if read_settings is None else read_settings
    files = FastMCP("binnacle-files", on_duplicate="error")
    read_file.register(files, roots=roots, settings=read_settings)
    list_files.register(files)
    edit_file.register(files)
    write_file.register(files, roots=roots)
    return files
