"""Focused Files server using the existing MCP adapters."""

from fastmcp import FastMCP

from binnacle.config import (
    EditFileSettings,
    ListFilesSettings,
    ReadFileSettings,
    RootsSettings,
    get_settings,
)
from binnacle.features.files.paths import FileToolAccess
from binnacle.features.files.tools import edit_file, list_files, read_file, write_file


def create_files_server(
    *,
    roots: RootsSettings | None = None,
    file_access: FileToolAccess | None = None,
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
    if roots is None:
        raise ValueError("File roots missing after configuration capture")
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
    files = FastMCP("binnacle-files", on_duplicate="error")
    read_file.register(
        files, file_access=file_access, roots=roots, settings=read_settings
    )
    list_files.register(
        files,
        file_access=file_access,
        roots=roots,
        settings=list_settings,
        rg_bin=rg_bin,
    )
    edit_file.register(
        files, file_access=file_access, roots=roots, settings=edit_settings
    )
    write_file.register(files, file_access=file_access, roots=roots)
    return files
