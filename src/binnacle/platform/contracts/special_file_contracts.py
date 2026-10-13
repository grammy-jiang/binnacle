"""Shared refusals of the file and search tools: one code and one text per OS pair.

SPECIAL_FILE_*: the refusal for a FIFO, socket or device. The file tools work
on regular files only. read_file, edit_file, write_file, list_files (list and
glob) and search_text refuse one with this code and text on both OSes: the
Linux tools directly, Darwin through error_text.linux_error, which words the
adapters' terse code (r6 W3 PX1). The text keeps the code as its first word,
so a caller that matched the old text ("special_file_unsupported.") still
finds it, and it tells the model what the path is and what to do instead.

TOO_MANY_OPEN_FILES_*: the refusal for a descriptor shortage (EMFILE/ENFILE),
which is never evidence about a path (SRC-W2-04, SD-79). One template for
list_files (list and glob), search_text and the Darwin adapters (PF-SP1-1);
only the tool, the task and the advice are filled in (r6 W3 PX1).
"""

from __future__ import annotations

import errno

# Some kernels refuse the open of a swapped-in socket/device *before* fstat.
# Classify only the exact descriptor-relative entry, never the absolute path.
SPECIAL_OPEN_ERRNOS = (
    errno.ENXIO,
    errno.ENODEV,
    errno.EOPNOTSUPP,
    errno.EACCES,
    errno.EPERM,
)
SPECIAL_FILE_CODE = "special_file_unsupported"
SPECIAL_FILE_TEXT = (
    f"{SPECIAL_FILE_CODE}: the path is a FIFO, socket or device, not a regular "
    "file; the file tools read and write regular files only. Do not retry it; "
    "use run_command (ls -l, stat) to see what it is."
)

TOO_MANY_OPEN_FILES_CODE = "too_many_open_files"
TOO_MANY_OPEN_FILES_ERRNOS = (errno.EMFILE, errno.ENFILE)
# The adapters' errno -> code table (Darwin file_traversal.native_errors).
SHORTAGE_CODES = dict.fromkeys(TOO_MANY_OPEN_FILES_ERRNOS, TOO_MANY_OPEN_FILES_CODE)
TOO_MANY_OPEN_FILES_TEXT = (
    "{tool} could not {task}: the server has too many open files. {advice}"
)


def too_many_open_files_text(tool: str, task: str, advice: str = "Retry.") -> str:
    """The one descriptor-shortage text, for every tool and both OSes."""
    return TOO_MANY_OPEN_FILES_TEXT.format(tool=tool, task=task, advice=advice)


# Shared, stable refusal texts. These constants are intentionally housed with
# SPECIAL_FILE_TEXT so Linux and Darwin emit byte-identical file refusals.
PATH_IS_DIRECTORY_CODE = "path_is_directory"
PATH_IS_DIRECTORY_TEXT = "Path is a directory, not a file: {shown}.{advice}"


def path_is_directory_text(shown: object, tool: str = "read_file") -> str:
    advice = "" if tool == "edit_file" else " Use list_files to browse it."
    return PATH_IS_DIRECTORY_TEXT.format(shown=shown, advice=advice)


PATH_CHANGED_CODE = "path_changed"
PATH_CHANGED_TEXTS = {
    "list_files": (
        "Directory changed during the listing: {shown}. "
        "A path component is no longer a directory; list it again."
    ),
    "search_text": (
        "Directory changed during the search: {shown}. "
        "A path component was replaced by a link; search it again."
    ),
    "write_file": "File changed while it was opened: {shown}. Write it again.",
}
PATH_CHANGED_DEFAULT = "File changed while it was opened: {shown}. Read it again."


def path_changed_text(shown: object, tool: str = "read_file") -> str:
    """Stable file identity-change text for every path-facing MCP tool."""
    return PATH_CHANGED_TEXTS.get(tool, PATH_CHANGED_DEFAULT).format(shown=shown)
