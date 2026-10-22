# E2.2 provenance classifier — independent technical review trail

**Limited technical GO only.** Not a task-level R1/R2/R3 annotation, historical-source replay or LSP efficacy claim. Reviewers operated read-only against synthetic source/tests and did not read actual private capture logs, task documents, agent sessions, SQLite or connected resources.

| Review round | Finding | Resolution |
| --- | --- | --- |
| Initial REWORK | Tool-name suffix matched unrelated MCP servers; partially scanned archives were called uniquely linked; repo/path contradictions and unanchored task IDs were conflated; case-insensitive or partial IDs matched documents; symlink session sources were allowed | Require an exact same-host tool name, fail-closed session completeness, all explicit per-call repository roots, same-call case-sensitive whole IDs, and reject symlink paths |
| First follow-up | Malformed session JSON and missing timestamp events could disappear and manufacture a unique match; task prefix after `.` still matched; parent session directories could be symlinked | Count malformed/undated records, reject ancestor symlinks and add negative fixtures |
| Second follow-up | Recursive `Path.rglob` could silently suppress unreadable child directories and leave a false unique match | Switch to `os.walk(..., onerror=...)`; any missing directory degrades all uniqueness claims |
| Third follow-up | An old file's filesystem mtime was silently taken as proof that it had no in-range event | Report older skipped files as **incomplete coverage** and forbid unique-match certification |
| Final source follow-up | Unknown timestamp tool messages could disappear while preserving uniqueness | Count unparsable potential tool/user events as incomplete; final scoped review **limited technical GO** |
| E2.2 local inspection | Default E2.2 called the E2.1 packet writer during checksum validation | Added `require_existing_checkpoint=True` **read-and-compare** path; a synthetic test denies all writers and verifies no file's size/mtime changes; versioned output |
| Final follow-up | Checkpoint read-only behavior and prior provenance fixes examined | Independent scoped reviewer **limited GO**; source lead results still explicitly unverified |

MacBook E2.2 synthetic suite passed on native CPython 3.10 and 3.14; no E2.2 production server runtime, three-host source package deployment, complete historical Agent transcript join or independent original task/Gold Answer acceptance was claimed.
