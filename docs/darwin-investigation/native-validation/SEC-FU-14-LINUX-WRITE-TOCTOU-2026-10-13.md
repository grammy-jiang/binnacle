# SEC-FU-14: Linux write/edit pathname race assessment (analysis only)

Date: 2026-10-13. Evidence source: R6 W3 integration candidate.
Method: read-only call-path analysis; no demonstration exploit, malicious
filesystem fixture, bypass attempt, or production write was performed.
This report deliberately does not revive the safeguard-flagged SEC-FU-14
experimental lane.

## Observed call paths

1. Linux write_file_impl, with file_access=None, uses resolve_path() to
   canonicalize and check a name against configured roots. Subsequently it
   checks is_dir/is_file/stat, creates parent directories with mkdir, then
   calls Path.write_bytes(data) on the resolved string. The Path is reopened
   independently at write time, not relative to an identity-pinned descriptor.
2. Linux edit_file_impl likewise resolves a path once, then obtains bytes
   through Path.read_bytes and eventually writes through Path.write_bytes.
   Its source-text matching is not an atomic compare-and-swap of the
   descriptor it previously read. There are independent resolution/open gaps.
3. On macOS, FileToolAccess/DarwinFileAccess routes writes through opened
   grants and directory_at() with no-follow traversal, then an fd-relative
   _replace() operation. This is a different and narrower race boundary.
4. The Linux fd_walk.open_verified function used by read_file provides a
   descriptor-based post-open validation only for reads. Reusing the Python
   pathname-based write path does not inherit that safety property.

## Threat model and severity

A principal capable of mutating the parent tree concurrently between the
root validation and the final open can change what the pathname designates.
A client using only edit_file/write_file may thereby write a different
same-UID-accessible object than the earlier name validation approved.
No claim of arbitrary privilege escalation is justified; normal Unix
filesystem permissions still apply. The same authenticated Binnacle server
also exposes run_command for some clients, making the configured Files roots
a tool-scope boundary rather than a strong untrusted-user sandbox.
Client-prefix visibility is not a security principal, and should not be
used to dismiss this narrower race in deployments that restrict tools.

Severity: MEDIUM under the documented trusted-same-UID environment;
potentially HIGH in any deployment treating ALLOWED_ROOTS as an adversarial
write sandbox. Such configurations must not be promoted as safe.

## Options

A. Document the race and explicit trust boundary: trivial change, no runtime
regression risk; does not prevent the race. Appropriate immediate disclosure.
B. Use the fd-walk to open an authorised parent by descriptor and implement
fd-relative create/replace with O_NOFOLLOW and identity checks. Requires
a designed cross-host write contract (create vs overwrite, parent creation,
symlink-to-in-root behavior, content encoding, edit conflict semantics,
atomic replacement and error words). More engineering and dual-host tests,
but the robust long-term direction.
C. Re-check the path after open or just before write: reduces some windows
but cannot prove confinement against a concurrent rename or retarget.
Not a substitute for (B), and should not be accepted as closing the threat.

## Decision and next implementation package

Keep (A) as the disclosed limitation, and implement (B) as an independently
reviewed follow-up lane, coordinated with FDW-A's one-walk API. Preserve the
current Linux read semantics and original eight MCP tools. Only the
actual protected descriptor and negative tests can justify claiming the
write race closed. This report is NOT such evidence.

No source files, service settings, live records, secrets, or production
processes were modified as part of this analysis.
