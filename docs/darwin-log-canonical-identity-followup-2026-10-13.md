# Issue #30: late canonical pathname replacement refusal

Date: 2026-10-13. Non-destructive archive finalizer hardening.

## Verified race

A source file is currently pruned only under an injected lifetime writer
hold after checking the checksum of a canonical compressed archive.

Before this patch, the resumed-canonical path verified compressed bytes
through an open descriptor, closed it, and later removed the raw source
without proving the canonical pathname *still named that inode*.
The new-publication path likewise checked a private temporary inode and
linked it to the canonical pathname, but did not check for a path swap
after that link and before raw removal.

An unrelated writer/maintenance actor with access to the same directory
could therefore replace the canonical path after verification. A genuine
future producer writer hold is NOT a directory-wide exclusive lock. The
verified compressed file and the actual retained pathname might diverge.

## Fixed behavior

The finalizer now pins the metadata of the *verified compressed inode*
and checks the canonical pathname's dev, inode, size, ctime, mtime,
owner, link count and 0600 regular-file mode one more time immediately
before removing the raw source. It never trusts filename equivalence
alone. A resumed canonical must have one hard link. The freshly published
canonical temporarily has two (canonical + the unique sibling temp link),
which the existing finalizer removes in cleanup.

A missing, swapped, symlinked, rewritten or otherwise changed canonical
now refuses source pruning. Existing raw bytes remain the source of truth.
The canonical archive is not overwritten, and concurrent forged
destinations are never repaired by deleting the original source.

## Test evidence and limitations

New regression tests inject the pathname replacement after the
canonical hash validation on BOTH the resumed and newly-published
branches, including a symlink and byte rewrite. Good compressed archives
still finalize correctly. Tests operate only on disposable directories and
cooperative fixture WriterHolds; no Binnacle production log was touched.

This is a fail-closed check, not a substitute for the independently held
J7 maintenance, MCP/Jobs RPC-admission, watchdog and actual launchd FD
writer-generation barriers still needed by Issue #30. A malicious
same-UID actor racing exactly between this final check and unlink remains
outside the declared cooperative threat model; directory ownership and
real maintenance serialization remain essential.
