"""Focused Files server using the existing MCP adapters."""

from fastmcp import FastMCP

from binnacle.config import (
    EditFileSettings,
    ListFilesSettings,
    ReadFileSettings,
    RootsSettings,
    get_settings,
)
from binnacle.tools import edit_file, list_files, read_file, write_file


def create_files_server(
    *,
    roots: RootsSettings | None = None,
    read_settings: ReadFileSettings | None = None,
    list_settings: ListFilesSettings | None = None,
    edit_settings: EditFileSettings | None = None,
    rg_bin: str | None = None,
) -> FastMCP:
    """Build an independent Files child for native FastMCP composition."""
    if any(
        value is None
        for value in (roots, read_settings, list_settings, edit_settings, rg_bin)
    ):
        defaults = get_settings()
        roots = defaults.roots if roots is None else roots
        read_settings = defaults.read_file if read_settings is None else read_settings
        list_settings = defaults.list_files if list_settings is None else list_settings
        edit_settings = defaults.edit_file if edit_settings is None else edit_settings
        rg_bin = defaults.rg_bin if rg_bin is None else rg_bin
    files = FastMCP("binnacle-files", on_duplicate="error")
    read_file.register(files, roots=roots, settings=read_settings)
    list_files.register(files, roots=roots, settings=list_settings, rg_bin=rg_bin)
    edit_file.register(files, roots=roots, settings=edit_settings)
    write_file.register(files, roots=roots)
    return files
