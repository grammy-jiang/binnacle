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
list_files (list and glob), search_text and the Darwin adapters; only the tool,
the task and the advice are filled in (r6 W3 PX1).
"""

from __future__ import annotations

SPECIAL_FILE_CODE = "special_file_unsupported"
SPECIAL_FILE_TEXT = (
    f"{SPECIAL_FILE_CODE}: the path is a FIFO, socket or device, not a regular "
    "file; the file tools read and write regular files only. Do not retry it; "
    "use run_command (ls -l, stat) to see what it is."
)

TOO_MANY_OPEN_FILES_CODE = "too_many_open_files"
TOO_MANY_OPEN_FILES_TEXT = (
    "{tool} could not {task}: the server has too many open files. {advice}"
)


def too_many_open_files_text(tool: str, task: str, advice: str = "Retry.") -> str:
    """The one descriptor-shortage text, for every tool and both OSes."""
    return TOO_MANY_OPEN_FILES_TEXT.format(tool=tool, task=task, advice=advice)
