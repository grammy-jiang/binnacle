# P3.3: Rootless Bubblewrap feasibility with real Pyright (Linux ARM64)

**Recorded:** 2026-10-23, Sextant Raspberry Pi 5, Linux
6.18.50+rpt-rpi-2712, Bubblewrap 0.12.0, Node v24.19.0,
Pyright Language Server 1.1.413. This is a **native, disposable synthetic
proof of feasibility only**, not a sandbox integrated into Binnacle or an
independent confinement certificate.

**Decision:** `explicit_trust_only` remains. **READ / untrusted roots /
public MCP tool exposure: NO-GO**.

## Procedure and observations

The test used a disposable directory with one small `source.py` containing
a known class and method. Only explicitly selected, previously installed
Node and Pyright trees were available inside the sandbox; the package and
synthetic workspace were read-only. The isolated process was launched using
the following command structure (operator-resolved paths substituted):

```bash
bwrap --unshare-all --new-session --die-with-parent --clearenv \
  --ro-bind /usr /usr \
  --symlink usr/bin /bin --symlink usr/lib /lib \
  --dir /opt \
  --ro-bind "$TRUSTED_NODE_TREE" /opt/node \
  --ro-bind "$TRUSTED_PYRIGHT_TREE" /opt/pyright \
  --dir /workspace --ro-bind "$DISPOSABLE_WORKSPACE" /workspace \
  --proc /proc --dev /dev --tmpfs /tmp \
  --setenv PATH /opt/node/bin --setenv HOME /tmp \
  --chdir /workspace -- \
  /opt/node/bin/node /opt/pyright/langserver.index.js --stdio
```

No installed service, project workspace, production configuration, or user
log was modified. The harness constructed Content-Length-framed JSON-RPC
messages and **waited for each response before sending the next request**.
The first batch-send approach exited nonzero before useful responses, so it
was replaced by a proper bidirectional session; only that subsequent
bidirectional run is considered successful.

| Control | Verified result | Boundary |
| --- | --- | --- |
| Rootless mount/user/process/network namespaces | Bubblewrap launched Node v24.19.0 | Not yet managed by Binnacle lifecycle |
| LSP `initialize` | Response with `capabilities` | One disposable Python fixture |
| LSP `textDocument/documentSymbol` | Response received without LSP error | Does not prove full capability semantics |
| LSP `shutdown` and `exit` | Response received; process exited code 0 | No escaped descendant/PID proof |
| Host-writable workspace file creation attempted in sandbox | Denied with `EROFS` | Only one observed write-path attempt |
| Connection to a known positive-control host loopback listener | Denied (reported `ECONNREFUSED`) | Only one host listener, not all IPC |
| Synthetic workspace source digest and entries | Unchanged, no unexpected entry | Not a hostile project tree |
| External host package/home access | Not explicitly mounted | Underlying OS policy and FDs need audit |

The raw LSP payload contained only artificial symbols and workspace URIs;
the evidence reported above is sanitized to exclude local absolute paths,
process metadata, and raw user content. Both refusal controls were exercised
against a positive host-side precondition: the workspace was owner-writable
outside the sandbox, and the host loopback listener accepted a host
connection before the sandbox probe was attempted.

## What remains before a READ security decision

1. **Process ownership integration:** the Binnacle
   `PrivatePyrightProcessOwner` still launches trusted Node directly.
   It must be tested with the exact admitted binary/package identity,
   Bubblewrap argument builder, workspace grants, initialization and
   shutdown semantics, and strict fail-closed behavior if Bubblewrap cannot
   apply its policy.
2. **Filesystem safety:** verify mount topology, hidden HOME and host
   credentials, symlinks/hardlinks, installed npm package and Node identities,
   read-only approved roots, tmp/cache boundaries, and path/mount TOCTOU.
3. **Process and resource boundaries:** demonstrate no escaped descendants,
   network namespace escapes, executable privilege escalation, inherited
   descriptors, unauthorized writes, CPU/memory exhaustion or orphaned child
   after parent cancellation/SIGKILL.
4. **Cross-platform parity:** a separate macOS synthetic Pyright session
   succeeded under limited Seatbelt write/network restrictions, but read
   confinement is **not** established. Do not generalize Linux results to
   Darwin or infer that the two launch profiles have equivalent authority.
5. **Independent review:** collect source-bound, signed reviewer evidence
   and link it to the exact upstream `multilspy` VCS pin, built artifact,
   selected Node/JS tree and Binnacle commit. Then use the P3.6 fail-closed
   importer to produce stage-specific raw witnesses; no proof from this
   standalone test can set the production admission flag.

This work only removes the earlier feasibility uncertainty that Pyright
could not initialize inside a rootless Bubblewrap filesystem/network
namespace. It does **not** close the P3.3 OS-confinement release gate.

## Separate macOS Seatbelt exploratory comparison (2026-10-23)

MacBook Pro (Darwin arm64, macOS kernel 27.0.0), Node v24.21.0 and installed
Pyright 1.1.413 completed a bidirectional synthetic LSP `initialize`,
`textDocument/documentSymbol`, `shutdown` and `exit` with process
exit code **0** under this **limited** Seatbelt profile:

`(version 1)(deny default)(allow process*)(allow mach-lookup)`
`(allow sysctl-read)(allow file-read*)(allow file-write* (subpath CACHE))`

The selected CACHE was disposable and operator-created. Direct synthetic
workspace mutation was denied with `EPERM`; a connection to a host loopback
listener (separately confirmed reachable by the host) was denied with
`EPERM`; the synthetic source hash was unchanged. The test invoked only the
selected Node and Pyright commands; descendant processes were not audited.
These observations are not
a full sandbox escape or process-tree audit.

**Critical missing constraint:** the observed working profile currently uses
`(allow file-read*)`, which lets the provider read unrelated host files.
Consequently it is **not suitable for READ security admission**. A stricter
read allowlist covering selected system paths but excluding arbitrary host
home files caused Node to abort before executing JavaScript. The necessary
Apple system read/mach rules and trusted package boundaries still require
separate debugging, source review and negative controls. In particular,
`allow mach-lookup` is broad and needs to be narrowed to independently
reviewed system services.

The read/write/network profile and subprocess/escape behavior have not been
integrated into `PrivatePyrightProcessOwner`. These two feasibility tests
(Linux Bubblewrap and macOS Seatbelt) **do not change READ/public NO-GO**.
