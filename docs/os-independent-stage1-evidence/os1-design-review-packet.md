# OS1 independent contract and safety review packet

Task ID: BINNACLE-OS-STAGE1-IMPLEMENT-20261009.

Status: REVIEW_PENDING. This packet is from the implementation owner, not
an independent approval. The production v1.0.1 baseline remains commit
02f4bab9bc7562668ffc41d622c4274449933768. The plan base remains commit
19a3cf1e43755ed4aee3837c25ea63188058a26e. The exact current candidate
SHA must be retrieved from Git before reviewing any changes.

## Architecture rules

- FastMCP 4.1.0 owns three mounted native child servers, Providers,
  Transforms, authentication, middleware, MCP lifespan and request-scoped DI.
- Commands owns durable Job Manager and RPC v1, not FastMCP Tasks.
- Linux adapters own signaling, procfs, cgroups, systemd, journald and XDG.
- Public Linux pid, pgid, starttime, boot_id, spool schema, combined log,
  stdout/stderr cursor and manager recovery remain unchanged.

## Baseline contract characterization

The adjacent os1-contract-capture.json records the SHA-256 and exported method
names of all five existing platform Protocol modules.

| Boundary | Minimum responsibility | Risk |
| --- | --- | --- |
| ProcessBackend | Launch, wait, owned identity, safe inspect/stop | P0 |
| ResourceAccounting | Optional containment, counters, cleanup | P0 |
| RuntimePaths | Runtime directory and jobs socket value | P1 |
| ManagedService | Read-only facts versus restart action | P0 |
| ServiceLogSource | Semantic epoch read and failure semantics | P1 |

## Proposed stop-identity contract, requires independent decision

Today, ProcessBackend.signal_job(pgid, strays, intent) receives native integer
identifiers only, without the recorded process generation. The earlier
alive(pid, starttime) check does not make a later killpg atomic. A group
leader may have exited, and PID/PGID reuse or an unrelated reparented child
can make an unchecked signal unsafe.

Proposal: a minimal opaque domain-facing JobProcessIdentity value carried
between job storage/state and the Linux adapter, with Linux-compatible pid,
pgid and starttime fields preserved in persisted metadata. Require backend
verification of owned targets immediately before each signal and fail closed
for uncertain identity, orphaned descendants or reused IDs. Cgroup
membership, where present, supplies containment evidence independently of
resource counters. Do not claim that read-then-killpg is intrinsically atomic.

A review must decide whether the Linux adapter can demonstrate sufficient
ownership in the leader-exit case, whether pidfd or cgroup references are
necessary, and what safe behavior to adopt for legacy records without
starttime. Require deterministic PID reuse, leader exit, strays, group-race
and manager-recovery negative tests. Do not silently weaken Linux behavior.

## Separate containment, service and application responsibilities

ResourceAccounting currently mixes argv wrapping and scope lifecycle with
counter snapshots. Avoid a new class hierarchy if focused tests can express
independent capabilities through existing Protocols. Do not introduce
FeatureRegistry, a second Provider router or lifecycle manager.

The OS-independent native FastMCP application constructor now receives
settings, token and durable CommandBackend explicitly. Linux bootstrap stays
in the existing public server module, and unsupported OS families fail
before adapter import. This is not evidence that OS3 lifecycle is complete.

For OS4 preserve systemd unit marker, diff, adopt/refuse, backup and service
activation order exactly. A minimal platform provisioning seam should
encapsulate only host-specific operations; generic policy must be testable
with fake services.

For OS5 canonical roots and candidate paths both resolve aliases prior to
comparison, maintaining escaping-symlink denial. This does not prove
filesystem operations immune to time-of-check/time-of-use swaps.
Log analysis no longer eagerly imports the Linux journal source.

## Independent review output required

Review the actual committed SHA, changed source, OS0 parity reference and
the five Protocol captures. Return APPROVE_DESIGN, REVISE or BLOCKED_POLICY
with evidence in four cells: process identity and stop safety; containment
versus counters; FastMCP and composition; service provisioning/test plan.
Record reviewer identity, reviewed SHA and date. Do not approve migration
based solely on this packet. Independent review is not currently recorded.
