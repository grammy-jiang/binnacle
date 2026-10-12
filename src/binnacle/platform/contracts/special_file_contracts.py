"""The refusal for a FIFO, socket or device: one code and one text for both OSes.

The file tools work on regular files only. Linux read_file refuses a special
file with this code and text; Darwin file_traversal.regular_fd raises the same
code, and its call site moves to this text in r6 W3 wave B (after OS1). Both
OSes import these constants, so the model-visible wording cannot drift between
them (FILES-FOLLOWUP-special-file-text). The text keeps the code as its first
word, so a caller that matched the old text ("special_file_unsupported.") still
finds it, and it tells the model what the path is and what to do instead.
"""

from __future__ import annotations

SPECIAL_FILE_CODE = "special_file_unsupported"
SPECIAL_FILE_TEXT = (
    f"{SPECIAL_FILE_CODE}: the path is a FIFO, socket or device, not a regular "
    "file; the file tools read and write regular files only. Do not retry it; "
    "use run_command (ls -l, stat) to see what it is."
)
