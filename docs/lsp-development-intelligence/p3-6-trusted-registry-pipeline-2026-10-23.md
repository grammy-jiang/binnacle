# P3.6 trusted reviewer registry and evidence-linking pipeline (private prototype)

**Date:** 2026-10-23. **Status:** conservative offline prototype. It
authenticates a *signed claim* against an operator registry. It grants **no**
authority: selection stays `REWORK`, resource `REWORK`, READ and public release
`NO-GO`, `attestations_verified=false`, `authority_granted=false`,
`os_confinement_accepted=false`. A verified `GO` claim is reported only as the
outcome `verified_approval`.

## Modules (see `p3-6-trust-chain-modules-2026-10-23.json`)

| Module | Role |
| --- | --- |
| `scripts/lsp_p36_secure_io.py` | Descriptor-relative walk with `O_NOFOLLOW` at every component. Refuses symlinks, hardlinks (`st_nlink != 1`), non-regular files, foreign owners, group/world-writable parents and files, setuid/setgid/sticky bits, size violations, files that change during the read, and any path whose directory chain contains a forbidden root (compared by device/inode, not by name). |
| `scripts/lsp_p36_trust_registry.py` | Strict registry schema, loader, key lifecycle, `MemoryReplayLedger`, `FileReplayLedger`. |
| `scripts/lsp_p36_signed_review.py` | Receipt v1 (self-contained proof of signature, **no authority**, unchanged) and receipt v2 `verify_registry_review`. |
| `scripts/lsp_p36_link.py` | P3.3/P3.4/P3.5 linking pipeline and CLI. The CLI never exits 0. |
| `scripts/lsp_p36_import.py` | Existing consistency preflight; now reads files through `secure_io`. Still not an attestation. |

## Trust model

- The registry path is explicit (`--registry` or `BINNACLE_P36_TRUST_REGISTRY`).
  **Nothing configured means `trust_registry_not_configured`.** There is no
  default path, no download and no key generation or enrollment.
- The CLI requires the registry file and every ancestor to be owned by **root**
  and not group/world-writable (no sticky shared ancestors). Library callers
  pass an explicit `PathPolicy`; only unit tests use process-owned temp roots.
- The registry must not sit in, or contain, any directory that holds supplied
  evidence, the repository checkout, or the working directory.
- Signer public key, principal and stage roles come **only** from the
  registry. A receipt supplies a `key_id`; unknown fields, embedded keys and
  roles are refused by the strict schema. `key_id` must equal the SHA-256 of
  the registry's raw public key.
- Lifecycle: `active`, `retired` and `revoked`. Fresh linkage refuses **all
  retired keys**, including backdated receipts (a stolen retired key can forge
  the issue timestamp). Revoked keys are also refused retroactively. Rotation requires
  the successor's `supersedes` to name a non-active predecessor. A deleted key
  is `signer_key_unknown`. Validity windows, `registry_id` and a caller-pinned
  minimum `serial` (rollback) are enforced.
- Role separation: a registry reviewer principal may not be a registry
  producer; the receipt reviewer must equal the key principal and differ from
  the producer.
- Receipt v2 signs: stage, key id, registry id, run id, reviewer, producer,
  Binnacle commit, target SHA-256, raw artifact SHA-256, evidence SHA-256,
  verdict and issue time under domain `BINNACLE:P3.6:ED25519:REVIEW:V2`.
- Replay: one receipt per `(registry_id, run_id, stage)`. Verification is
  two-phase: all three stages verify, then keys are recorded together, so a
  failed link burns nothing. `MemoryReplayLedger` reports
  `replay_protection=ephemeral`.
- Linking requires exactly P3.3, P3.4 and P3.5, one shared run, commit and
  target, pairwise distinct raw artifacts, and a receipt that matches each
  artifact's SHA-256.

## Tests

`tests/scripts/test_lsp_p36_{secure_io,trust_registry,link,trust_chain_manifest}.py`
use ephemeral, test-only Ed25519 keys and separate temporary operator,
evidence and state roots. No network or shell is used. Covered: valid external
signer; wrong and injected keys; spoofed self-reviewer; revoked, deleted,
rotated/retired and role-limited keys; stale/future; duplicate/unknown JSON;
improper owner and mode; symlink and hardlink paths; registry among evidence;
replay across ledger instances; identity, altered-artifact, cross-stage and
missing-evidence refusals; unconfigured registry; CLI refusal of a
process-owned registry; and an AST check that the modules import no network,
process or temp-file modules.

## Truthful blockers (still open)

1. **Registry provenance is not provable here.** The sandbox runs as the same
   account as the agent. Any file that account owns is agent-writable, so a
   real operator registry needs a separate (root or dedicated) owner. The
   unit tests simulate this with process-owned temp roots and therefore prove
   the checks, not the provenance. `registry.owner_is_current_user` is
   reported in every result; the CLI refuses a process-owned registry.
2. The registry has no offline signature or hardware root. Its integrity is
   exactly filesystem ownership; root or kernel compromise defeats it.
3. `FileReplayLedger` and the serial pin live under the same account unless
   the operator isolates them. Replay and rollback protection are therefore
   not tamper-resistant against a same-account attacker.
4. The clock is the local system clock.
5. No real independent reviewer key exists, and no raw independent stage
   evidence was produced. A signed approval does not establish OS
   confinement, Pyright method identity or resource limits.
6. Linking checks signed claims against the bytes. It does not re-run P3.3
   isolation or P3.5 measurement, and it does not feed `lsp_p36_policy`.
7. No MCP tool, production registration, deployment or READ enablement.

## Independent-review follow-up, 2026-10-23

The independent read-only P3.6 source review identified high-priority
configuration-pin and error-handling flaws. Follow-up candidate code now
requires an **explicit** registry serial floor and an **exact SHA-256** pin.
The pin is supplied by an operator and is not itself a separate trust anchor;
the signed claims still grant no authority. The CLI now returns a sanitized
NO-GO `internal_error` code for unexpected failures. Calendar-invalid and
deeply nested receipt inputs fail closed without printing source paths or
contents. A replay ledger must already exist; the verifier never creates a
fresh one. Multi-part writes are written to completion, and both the ledger
and its parent directory are fsynced. Torn rows are rejected.

The ledger and registry must be provisioned by an independently trusted
operator. A same-user application can still replace its own ledger state;
there is **no** authenticated external ledger anchor in this prototype.
A caller-selectable ledger path remains a replay-weakness even when the file
is pre-provisioned. This is independently documented as a release blocker,
and real approval/READ remain NO-GO.

For current linking a retired key is rejected even for a historically dated
receipt; this prevents a stolen retired key from backdating fresh signatures.
Replay SHA identifiers keep their original format for compatibility but reject
embedded NUL separators rather than silently changing existing ledger keys.
