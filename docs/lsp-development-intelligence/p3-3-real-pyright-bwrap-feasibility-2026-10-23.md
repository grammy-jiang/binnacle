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
4. **Cross-platform parity:** macOS `sandbox-exec` is installed on the
   MacBook Pro but its complete Pyright policy and lifecycle have **not** been
   verified. Do not generalize Linux results to Darwin.
5. **Independent review:** collect source-bound, signed reviewer evidence
   and link it to the exact upstream `multilspy` VCS pin, built artifact,
   selected Node/JS tree and Binnacle commit. Then use the P3.6 fail-closed
   importer to produce stage-specific raw witnesses; no proof from this
   standalone test can set the production admission flag.

This work only removes the earlier feasibility uncertainty that Pyright
could not initialize inside a rootless Bubblewrap filesystem/network
namespace. It does **not** close the P3.3 OS-confinement release gate.
