# macOS launchd log rotation: preserve open-writer bytes

Date: 2026-10-13. Runtime scope: MacBook Pro Binnacle LaunchDaemons.
The original Raspberry Pi and sextant journald retention are unchanged.

## Why bzip2-on-rotation was unsafe

A LaunchDaemon with `StandardOutPath` or `StandardErrorPath` keeps its
file descriptor open. Standard macOS `newsyslog` with `GNJ` renames the
log and immediately compresses it; launchd's writer is not signalled. In
a privileged **temporary test fixture only** (not a real Binnacle service),
writes through the original descriptor after compressed rotation were
absent from both the new file and the compressed archive.

The real log source of truth is the original inode, not the filename.
Copy-and-truncate also introduces a write/clear race and is **not** an
acceptable purported lossless replacement.

## Implemented rename-only policy

The new policy uses the `GN` flags:

- `G`: glob of Binnacle `*.log` files;
- `N`: no signal, because arbitrary SIGHUP would be unsafe to the daemon;
- **no `J`, `Z` or post-rotation compression** on a potentially live inode.

In a separate macOS test fixture using actual
`sudo newsyslog -F -f <private-fixture>`, rename-only rotation produced a
new empty `.log`, while the original descriptor continued writing to
`.log.0`. The new writes were present in `.log.0` afterward, not lost.
A second temporary-fixture experiment used the actual `GN` *glob* rule for
MCP and Jobs logs simultaneously; both preserved bytes written after the
rename through their original descriptors. No production logs were touched.
A separate automatic test asserts that the production log reader includes
those later `.log.0` events even when `.log` is empty.

The Darwin resource monitor now checks **both** active `.log` and raw
rotated `.log.N` files. It warns when either exceeds its threshold and
tightens the permissions on both to `0600`. It intentionally ignores
old `.log.N.bz2` historical files for *growth* warnings: they cannot
grow through launchd's active writer under the supported mechanism.

This fixes the immediate compressor-versus-open-writer loss in the
**rotation step**, but does not constitute a complete machine crash or
power-loss durability guarantee. A raw `.log.0` may grow beyond the
active-log threshold until launchd safely reopens the new active path.

### Large-capacity Mac SSD sizing

At rollout, 12 native `*.log` streams were observed; 2.4 TiB was
available on the 3.6 TiB Mac filesystem.

| Setting | New | Previous |
| --- | --- | --- |
| Automatic rename-only threshold per active file | **50 GiB** | 10 GiB |
| Early warning for active or raw-archive file | **40 GiB** | 8 GiB active only |
| Archived generations | **2** | 7 |
| Compression during rotation | **none** (`GN`) | bzip2 (`GNJ`) |
| Minimum free-disk warning | **100 GiB** | 100 GiB |
| File permissions | **0600** | 0600 |

The reduction from 7 to 2 archive generations is deliberate:
`12 streams × (1 active + 2 raw archives) × 50 GiB = 1,800 GiB`
of projected uncompressed nominal capacity. This is **not a strict cap**:
writers can continue appending to a rotated archive. Seven 50 GiB
generations across 12 streams would have a nominal 4,800 GiB budget,
larger than the Mac's available disk. The reserve warning addresses
growth before exhausting space, but it cannot prevent disk exhaustion.

Existing compressed archives remain readable by `binnacle stats`; the
new policy does not delete them during deployment. No services are
restarted or log files force-rotated to apply this policy.

## Remaining offline compression / cleanup work

Do **not** compress, truncate or remove a raw `.log.0` which may
still be held open. Compression is permissible only after the relevant
producer has safely closed its descriptor, under an agreed
maintenance/quiet-window lifecycle. A safe finalizer should:

1. Determine the authoritative producer and confirm that it has finished
   writing the old archive; failure or unknown must refuse.
2. Verify inode, owner, link count, file size and mode with no symlinks.
3. Compress to a unique temporary file in the same filesystem, then
   validate decompressed size and checksum against the stable source.
4. Revalidate writer cessation and source metadata before any deletion.
5. Atomically publish the verified compressed archive, remove the raw
   source only while the producer remains quiesced, and confirm that the
   usage log reader sees exactly one copy.

This maintenance finalizer is **not automatically enabled**: there is no
atomic producer-maintenance contract shared with launchd, and no
reliable justification to interrupt the currently running development jobs.

## Safe deployment procedure

1. Implement and test in a private Git worktree, including simulated
   writes after a rename-only rotation and archive ingestion.
2. Merge through protected GitHub PR only after all required checks.
3. Verify the installed config's precise original bytes; back it up to
   the user's private state directory and atomically replace just the
   Binnacle-owned `newsyslog` rule.
4. Run `sudo newsyslog -n -v -f /etc/newsyslog.d/com.binnacle.mcp.conf`
   to ensure the new `GN` policy is understood. **Never** invoke
   `-F` on Binnacle production logs during this deployment.
5. Restart **only** the standalone Mac resource monitor to activate
   the new warnings; preserve the existing MCP, Jobs, Tunnel and
   service-watchdog PIDs.
6. Defer actual host reboot, runtime tokenizer/manager upgrade and
   fault injection until active jobs and unrelated development are
   truly quiescent.

## Follow-up: verified offline compressed staging

A separate `darwin_log_archive_stage` module can generate an integrity-
verified `.bz2.pending` snapshot of a raw archive without changing or
deleting the writer's source inode. It is an **explicit manual operation**,
not a service or automatic pruning process. Pending copies are excluded
from the statistics reader so metrics are not doubled. See
[darwin-log-archive-staging-2026-10-13.md](darwin-log-archive-staging-2026-10-13.md).

Deletion or promotion of raw archives is still gated by a demonstrated
writer-coordinated quiet window; no one-shot lsof observation is sufficient
to prove a stream can never be reopened.
