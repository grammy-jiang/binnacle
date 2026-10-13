# SEC-FU-14: Linux FD-relative write/edit implementation and trust boundary

Date: 2026-10-13. Follow-up to
[SEC-FU-14 assessment](darwin-investigation/native-validation/SEC-FU-14-LINUX-WRITE-TOCTOU-2026-10-13.md).
Scope: Linux `write_file`/`edit_file` only; no new MCP tools, configuration
knobs, host restarts or changes to the Darwin provider.

## Contract

- The existing `resolve_path` call only supplies an allowed canonical
  *candidate* and the historical display path. In-root symlink aliases
  follow the same initial policy as before. It is not relied on as write
  authority.
- Open the **most specific containing canonical root** by the existing
  `fd_walk.open_root` from `/`. Walk below the held directory descriptor
  using `O_PATH|O_DIRECTORY|O_NOFOLLOW`; create missing parent components
  using `mkdirat` with the held parent (no path-based `mkdir -p`).
- Never reopen the candidate as an absolute path to read or write. Open
  the final component relative to the held parent, `O_NOFOLLOW` and
  `O_NONBLOCK`, check the actual descriptor is a regular file, and refuse
  links, directories and special files. Read/edit only that verified FD.
- Generate an exclusive private temporary sibling; write all UTF-8 bytes
  without newline/BOM transformation, `fsync` and atomically `renameat`
  to the destination. Keep the previous mode and receipt sizes.
- For edits, compare original content SHA-256 **and** the inode/device of
  the object initially read, and recheck the destination immediately before
  replacement. Report any observed conflict instead of overwriting it.
  Overwrite is atomic publication, not an atomic CAS on an adversarial writer.
- Check that the held parent has its expected canonical location using the
  Linux `/proc/self/fd` descriptor reference before and after preparing the
  replacement. This fails closed for *observed* parent renames, deleted
  parents and other retargets. It never follows a symlink introduced at the
  final component and never writes through such a link.
- Preserve missing-edit, path-outside-root, directory/special-file, legacy
  permission message and create/overwrite response semantics. Linux changes
  existing file inodes through atomic replacement instead of truncating them
  in place. This is an intentional difference to prevent partial output.

## Threat boundary and exclusions

The principal operating the service and any process able to mutate the
authorized tree run as the same trusted UID. An FD-relative transaction pins
the directory that was opened, **not its continuous membership under a
pathname**. The kernel cannot guarantee confinement against a fully hostile
same-UID writer who renames an opened parent after the last location check
but before `renameat`, or who changes file bytes concurrently during the
last non-atomic comparison. A check of `/proc/self/fd` narrows observable
moves but does not make those operations atomic with the check.

**ALLOWED_ROOTS must not be advertised as a security sandbox against an
adversary controlling the same-UID filesystem namespace.** Stronger
isolation requires separate Unix users/mount namespaces and least-privilege
service credentials. The Linux read implementation and Darwin's opened
grant provider remain unchanged.

## Acceptance checklist

- Targeted unit fixtures create nested parents; exercise UTF-8/empty/CRLF,
  successful in-root symlinks, outside symlinks, injected final link swap,
  parent rename + external retarget, same-content inode swap, edit content
  conflict, FIFO/special/directory, error wording, permissions and short
  writes, all under temporary test roots.
- Mac/Darwin regression checks prove that the platform dispatch remains
  unchanged; Linux regression checks prove the new FD branch is actually
  exercised. Run the contract/security suites and protected CI before merge.
- No production filesystem attack demonstration, `sudo`, live service
  restart, or host reboot belongs to this implementation.
