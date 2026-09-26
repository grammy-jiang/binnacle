"""read_files — read several text files in one call (docs/tools/read_files.md).

Two candidates under evaluation (2026-09-27), off by default
(read_file.multi_mode): "tool" registers read_files, "param" gives read_file a
files argument. Both return read_files_impl's result, which reuses read_file's
per-file steps (_load, _window, _serve) for every entry.
"""

from dataclasses import dataclass
from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.tools.base import ToolResult
from pydantic import BaseModel, ConfigDict, Field

from binnacle.config import get_settings
from binnacle.errors import CodedToolError
from binnacle.tools import read_file as rf

MULTI_MAX_FILES = get_settings().read_file.multi_max_files  # files per call
MULTI_BUDGET_CHARS = get_settings().read_file.multi_budget_chars  # shared budget
MULTI_MIN_SHARE_CHARS = 4_000  # per read file, else the last files are not read

REQUEST_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "start_line": {"type": "integer"},
        "end_line": {"type": "integer"},
    },
    "required": ["path"],
}
ENTRY_SCHEMA = {
    "type": "object",
    "properties": {
        **rf.OUTPUT_SCHEMA["properties"],
        "index": {"type": "integer"},
        "kind": {
            "type": "string",
            "enum": ["text", "binary", "empty", "error", "not_read", "duplicate"],
        },
        "budget_cut": {"type": "boolean"},
        "error": {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "message": {"type": "string"},
            },
            "required": ["code", "message"],
        },
        "not_read": {"type": "boolean"},
        "request": REQUEST_SCHEMA,
        "duplicate_of": {"type": "integer"},
    },
    "required": ["index", "path", "kind"],
}
MULTI_PROPERTIES: dict[str, Any] = {
    "kind": {"type": "string", "enum": ["files"]},
    "files": {"type": "array", "items": ENTRY_SCHEMA},
    "files_requested": {"type": "integer"},
    "files_read": {"type": "integer"},
    "files_failed": {"type": "integer"},
    "files_not_read": {"type": "integer"},
    "files_duplicate": {"type": "integer"},
    "truncated": {"type": "boolean"},
    "chars": {"type": "integer"},
    "budget_chars": {"type": "integer"},
    "next_call": {
        "type": "object",
        "properties": {"files": {"type": "array", "items": REQUEST_SCHEMA}},
        "required": ["files"],
    },
    "note": {"type": "string"},
}
MULTI_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": MULTI_PROPERTIES,
    "required": [
        "kind",
        "files",
        "files_requested",
        "files_read",
        "files_failed",
        "files_not_read",
        "truncated",
    ],
}
PARAM_OUTPUT_SCHEMA = {  # candidate "param": read_file returns either shape
    "type": "object",
    "properties": {
        **rf.OUTPUT_SCHEMA["properties"],
        **MULTI_PROPERTIES,
        "kind": {"type": "string", "enum": ["text", "binary", "empty", "files"]},
    },
    "required": ["kind"],
}


class FileRange(BaseModel):
    """One entry of a multi-file read (the same fields as a read_file call)."""

    model_config = ConfigDict(extra="forbid")

    path: Annotated[str, Field(description=rf.PATH_DESCRIPTION)]
    start_line: Annotated[int, Field(ge=1, description=rf.START_LINE_DESCRIPTION)] = 1
    end_line: Annotated[
        int | None, Field(ge=1, description=rf.END_LINE_DESCRIPTION)
    ] = None


def budget_phrase() -> str:
    """How the shared budget works, for both candidates' descriptions."""
    return (
        f"read in order under one {MULTI_BUDGET_CHARS // 1000}k-char budget: "
        "small files come back whole, larger ones are cut and give "
        "next_start_line. Each entry succeeds or fails on its own (kind, "
        "error); entries the budget cannot reach come back not_read, and "
        "next_call holds the arguments to continue."
    )


def description() -> str:
    """read_files' description (candidate "tool")."""
    return (
        "Read several known text files in one call: up to "
        f"{MULTI_MAX_FILES} entries of path, start_line, end_line (1-based, "
        "inclusive), "
        + budget_phrase()
        + " Content matches read_file: plain text without line numbers; binary "
        "files return a note."
    )


def param_description() -> str:
    """read_file's description in candidate "param"."""
    return (
        rf.DESCRIPTION
        + " To read several known files in one call, pass files instead of "
        + f"path (up to {MULTI_MAX_FILES} entries of path, start_line, end_line), "
        + budget_phrase()
    )


@dataclass
class _Entry:
    """One requested file on its way through a multi-file read."""

    index: int
    request: dict
    payload: dict | None = None  # final: binary, empty, error, duplicate
    text: Any = None  # read_file._TextFile when the file decoded to text
    want: int = 0  # chars a one-file read would serve


def _request(entry: FileRange | dict) -> dict:
    raw = entry.model_dump() if isinstance(entry, FileRange) else dict(entry)
    req = {"path": raw["path"], "start_line": raw.get("start_line") or 1}
    if raw.get("end_line") is not None:
        req["end_line"] = raw["end_line"]
    return req


def _fill(entries: list[_Entry], budget: int) -> dict[int, int]:
    """Water-filling: the smallest wants are met first and every other file
    gets an equal share of what is left."""
    alloc: dict[int, int] = {}
    remaining, left = budget, len(entries)
    for e in sorted(entries, key=lambda e: (e.want, e.index)):
        share = remaining // left
        alloc[e.index] = min(e.want, share)
        remaining -= alloc[e.index]
        left -= 1
    return alloc


def _phrase(payload: dict) -> str:
    """One entry's outcome for the text summary."""
    kind = payload["kind"]
    if kind == "text":
        start, end, total = (
            payload["start_line"],
            payload["end_line"],
            payload["total_lines"],
        )
        span = (
            f"all {total} lines"
            if start == 1 and end == total
            else f"lines {start}-{end} of {total}"
        )
        if payload.get("truncated"):
            span += f", continue at {payload['next_start_line']}"
            if payload.get("budget_cut"):
                span += " (budget)"
        return span
    return {
        "binary": f"binary ({payload.get('mime_guess')})",
        "error": f"error {(payload.get('error') or {}).get('code')}",
        "not_read": "not read (budget)",
        "duplicate": f"same as entry {payload.get('duplicate_of')}",
    }.get(kind, kind)  # empty


def _load_entry(e: _Entry, seen: dict[tuple[str, int, int | None], int]) -> None:
    """Load one entry: a final payload (error, binary, empty, duplicate) or
    decoded text with its want."""
    req = e.request
    try:
        loaded = rf._load(req["path"], req["start_line"], req.get("end_line"))
    except CodedToolError as err:
        code = getattr(err, "telemetry_code", "error")
        e.payload = {
            "path": req["path"],
            "kind": "error",
            "error": {"code": code, "message": str(err)},
        }
        return
    except OSError as err:
        e.payload = {
            "path": req["path"],
            "kind": "error",
            "error": {
                "code": "read_error",
                "message": f"Could not read {req['path']}: {err.strerror or err}.",
            },
        }
        return
    resolved = loaded[1]["path"] if isinstance(loaded, tuple) else str(loaded.resolved)
    key = (resolved, req["start_line"], req.get("end_line"))
    if key in seen:
        e.payload = {
            "path": resolved,
            "kind": "duplicate",
            "duplicate_of": seen[key],
            "note": f"Same file and range as entry {seen[key]}; not repeated.",
        }
        return
    seen[key] = e.index
    if isinstance(loaded, tuple):
        e.payload = loaded[1]
    else:
        e.text = loaded
        e.want = rf._window(loaded, rf.READ_MAX_CHARS)[2]


def _allocate(entries: list[_Entry], budget: int) -> dict[int, int]:
    """Char allowance per readable entry; the entries left out are not read."""
    kept = [e for e in entries if e.text is not None]
    alloc = _fill(kept, budget)
    while len(kept) > 1 and any(
        alloc[e.index] < min(e.want, MULTI_MIN_SHARE_CHARS) for e in kept
    ):
        kept.pop()  # the last file in request order waits for the next call
        alloc = _fill(kept, budget)
    return alloc


def _finish(e: _Entry, alloc: dict[int, int], budget: int, next_files: list) -> None:
    """Serve a readable entry within its allowance, or mark it not_read."""
    if e.index not in alloc:
        e.payload = {
            "path": str(e.text.resolved),
            "kind": "not_read",
            "not_read": True,
            "request": e.request,
            "note": (
                f"Not read: this call's {budget // 1000}k-char budget went to "
                "the files before it. Request it again (next_call)."
            ),
        }
        next_files.append(e.request)
        return
    _summary, payload = rf._serve(e.text, max(alloc[e.index], 1))
    if alloc[e.index] < e.want:
        payload["budget_cut"] = True
        cont = {"path": payload["path"], "start_line": payload["next_start_line"]}
        if e.request.get("end_line") is not None:
            cont["end_line"] = e.request["end_line"]
        next_files.append(cont)
        cut_note = (
            f"Cut to share this call's {budget // 1000}k-char budget; "
            f"continue with start_line={payload['next_start_line']}."
        )
        payload["note"] = (
            f"{payload['note']} {cut_note}" if payload.get("note") else cut_note
        )
    e.payload = payload


def read_files_impl(files: list[FileRange] | list[dict]) -> ToolResult:
    """Read several files in order under one shared char budget.

    Per-file problems become that entry's error and never fail the call.
    Every file that is read gets its whole want or at least
    MULTI_MIN_SHARE_CHARS; when the budget cannot give that to every file,
    the last files come back not_read with the arguments to request them.
    """
    requests = [_request(f) for f in files]
    if not requests:
        raise CodedToolError("files_empty", "files is empty: give at least one path.")
    if len(requests) > MULTI_MAX_FILES:
        raise CodedToolError(
            "too_many_files",
            f"{len(requests)} files requested; at most {MULTI_MAX_FILES} per call. "
            f"Split the list over several calls.",
        )
    budget = MULTI_BUDGET_CHARS
    entries = [_Entry(index, req) for index, req in enumerate(requests)]
    seen: dict[tuple[str, int, int | None], int] = {}
    for e in entries:
        _load_entry(e, seen)
    alloc = _allocate(entries, budget)
    next_files: list[dict] = []
    for e in entries:
        if e.text is not None:
            _finish(e, alloc, budget, next_files)
    payloads = [{"index": e.index, **(e.payload or {})} for e in entries]

    count = {
        k: sum(1 for p in payloads if p["kind"] == k)
        for k in ("error", "not_read", "duplicate")
    }
    files_read = len(payloads) - sum(count.values())
    chars = sum(len(p.get("content", "")) for p in payloads if p["kind"] == "text")
    cut = sum(1 for p in payloads if p.get("budget_cut"))
    result: dict = {
        "kind": "files",
        "files": payloads,
        "files_requested": len(requests),
        "files_read": files_read,
        "files_failed": count["error"],
        "files_not_read": count["not_read"],
        "files_duplicate": count["duplicate"],
        "truncated": any(p.get("truncated") for p in payloads) or count["not_read"] > 0,
        "chars": chars,
        "budget_chars": budget,
    }
    notes = []
    if cut or count["not_read"]:
        notes.append(
            f"{cut} file(s) cut and {count['not_read']} not read to stay within "
            f"the {budget // 1000}k-char budget; next_call has the arguments to continue."
        )
    if count["error"]:
        notes.append(f"{count['error']} file(s) failed; see each entry's error.")
    if next_files:
        result["next_call"] = {"files": next_files}
    if notes:
        result["note"] = " ".join(notes)
    summary = (
        f"Read {files_read} of {len(requests)} files ({chars} chars): "
        + "; ".join(f"{p['path']}: {_phrase(p)}" for p in payloads)
        + "."
    )
    return ToolResult(content=summary, structured_content=result)


def effective_client_tools(
    client_tools: dict[str, tuple[str, ...]], multi_mode: str | None = None
) -> dict[str, tuple[str, ...]]:
    """In multi_mode "tool", read_files follows read_file into every client
    allowlist that serves read_file; otherwise the allowlists are unchanged."""
    if (multi_mode or rf.MULTI_MODE) != "tool":
        return client_tools
    return {
        prefix: (
            (*tools, "read_files")
            if "read_file" in tools and "read_files" not in tools
            else tools
        )
        for prefix, tools in client_tools.items()
    }


def register(mcp: FastMCP, multi_mode: str | None = None) -> None:
    """Candidate "tool": a separate read_files tool (nothing in other modes)."""
    if (multi_mode or rf.MULTI_MODE) != "tool":
        return

    @mcp.tool(
        description=description(),
        annotations={"readOnlyHint": True, "openWorldHint": False},
        output_schema=MULTI_OUTPUT_SCHEMA,
    )
    def read_files(
        files: Annotated[
            list[FileRange],
            Field(
                min_length=1,
                max_length=MULTI_MAX_FILES,
                description=f"1-{MULTI_MAX_FILES} files, read in this order.",
            ),
        ],
    ) -> ToolResult:
        """See description() (shipped text; interpolates the limits)."""
        return read_files_impl(files)


def register_param(mcp: FastMCP) -> None:
    """Candidate "param": read_file takes either path or files."""

    @mcp.tool(
        description=param_description(),
        annotations={"readOnlyHint": True, "openWorldHint": False},
        output_schema=PARAM_OUTPUT_SCHEMA,
    )
    def read_file(
        path: Annotated[
            str | None,
            Field(description=rf.PATH_DESCRIPTION + " Omit it when you pass files."),
        ] = None,
        start_line: Annotated[
            int, Field(ge=1, description=rf.START_LINE_DESCRIPTION)
        ] = 1,
        end_line: Annotated[
            int | None,
            Field(ge=1, description=rf.END_LINE_DESCRIPTION),
        ] = None,
        files: Annotated[
            list[FileRange] | None,
            Field(
                min_length=1,
                max_length=MULTI_MAX_FILES,
                description=(
                    f"Several files instead of path: 1-{MULTI_MAX_FILES} entries, "
                    "read in this order."
                ),
            ),
        ] = None,
    ) -> ToolResult:
        """See param_description() (shipped text; interpolates the limits)."""
        if path is not None and files is not None:
            raise CodedToolError(
                "path_and_files", "Give path (one file) or files (several), not both."
            )
        if files is not None:
            if start_line != 1 or end_line is not None:
                raise CodedToolError(
                    "range_with_files",
                    "start_line and end_line apply to path; with files, put the "
                    "range in each entry.",
                )
            return read_files_impl(files)
        if path is None:
            raise CodedToolError(
                "path_or_files_missing",
                "Give path (one file) or files (a list of path, start_line, end_line).",
            )
        return rf.read_file_impl(path, start_line, end_line)
