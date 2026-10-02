"""Focused Files server using the existing MCP adapters."""

from fastmcp import FastMCP

from binnacle.tools import edit_file, list_files, read_file, write_file


def create_files_server() -> FastMCP:
    """Build an independent Files child for native FastMCP composition."""
    files = FastMCP("binnacle-files", on_duplicate="error")
    read_file.register(files)
    list_files.register(files)
    edit_file.register(files)
    write_file.register(files)
    return files
