# Revision 1.2.0 (R4 J0): Darwin durable-job owner

Revision `binnacle-darwin-r4-interface-1.2.0`, source base
`9f958798bf9cbe289ad4cc8daa0714bbb8d0a305`. This is a proposal: the Supervisor
must review the exact signed commit before J1, J2 or J4 consume it (JCR-1). It
does not enable any tool. CI or review status from earlier SHAs does not carry
over to this commit.

| Amendment | Resolution |
| --- | --- |
| JCR-1 | No new `CapabilityState`. A full-with-disclosure row is `AVAILABLE` plus `decision_target="full_with_disclosure"` plus non-empty `ReleaseDecision.disclosures` (D-1, D-2, `descendants_unverified=true`). `validate_release_rows` refuses anything else. |
| JCR-1 table | Owner-keyed rows: `DARWIN_EMBEDDED_RELEASE_SCOPE` is the unchanged LIMITED table; `DARWIN_MANAGER_RELEASE_SCOPE` keeps file rows and commits the three command rows as `UNAVAILABLE` (`review_pending`, gate `J-CR`). |
| JCR-2 | `resolve_darwin_job_owner`: `auto` and `manager` give the manager; `embedded` only when configured. Rows follow the composed owner, never reachability. An unreachable manager is a per-call `job manager unavailable` error. The manager never serves LIMITED rows or composes an embedded execution. |
| `composition.py:261` | The unconditional stop_job assertion became `validate_owner_command_states`: embedded keeps stop_job `UNAVAILABLE` on every host; manager allows only `UNAVAILABLE`/`AVAILABLE`, and job tools need `run_command` `AVAILABLE`. |
| DarwinJobOwner | Frozen protocol in `process_contracts.py`: `spawn`, `wait`, `reap_exits` (kqueue NOTE_EXIT, sole reaper), `signal_owned_group`, `authority` (`OWNED`/`UNKNOWN`), `close`. |
| R4-REQ-J1J2-no-orphans | `close` is the normal owner stop: owned groups get terminate, the Linux grace, then kill; leaders are reaped and recorded with `owner_restart`. An unreapable group stays UNKNOWN. |

The machine-readable change list is `api-contract.json#/revision_1_2_0`. Linux
engine paths and every 1.1.0 declaration are unchanged; all additions are new
names or defaulted keyword parameters.

## Revision 1.1.0 resolution map (history)

All entries are author-proposed design resolutions, pending exact signed-commit
Supervisor review. No native implementation or acceptance is claimed.

| Finding | Resolution | Evidence keys |
| --- | --- | --- |
| A0-R0-01 / CR0-01 | All Darwin runtime states unavailable/disabled; conjunctive promotion gate and negative fixture | E1, E2 |
| A0-R0-02 / CR0-02 | Unique executor and joiners; durable prepare/resolution; terminal guards, crash recovery, retention and fencing | E3, E4, E5, E6 |
| A0-R0-03 / CR0-03 | FULL_PARITY_NO_GO with per-tool scope and packet propagation | E1, E2, E7 |
| CR0-04 | A2 foreground posix_spawn/live-owner/unreaped-leader target; R1 plus CR1 gate, escaped descendants unverified; background/over-limit denied | E1, E2, E7, E8 |
| R0-C2 / CR0-05 | A1 exclusively owns Linux stop/store/owner/reaper/RPC/retention; B0a owns shared declarations only | E1, E3, E4, E5, E6 |
| R0-C4 / CR0-06 | All five descriptor entrypoints, safe parent creation/hints, exact B0 wiring | E1, E2, E9, E10 |
| R0-C9 / CR0-07 | Every new test module starts test_; no collection hook; exact renamed cards and B0a phase | E1, E11 |

B0a begins only after CR0 APPROVE and may overlap A1. Accepted B0a declarations
precede A2–A6/T0 and A1 compile checks. B0a and B0 integration never overlap.
This resolves the dispatch dependency without concurrent shared-file writers.

Evidence paths below are relative to the run `inputs/` directory or repository
at the stated immutable source commit. Each JSON also carries full per-finding
`revision_evidence` objects; this table is a compact navigation aid. CR0-04 is
a binding architecture decision, not a claim that N2 proved foreground safety.
The Supervisor receipt supplied abbreviated hashes for the old documents;
validation uses actual final bytes and full hashes, never those abbreviations.

## Evidence

- **E1** (inputs): `cr0/CR0-SUPERVISOR-REVIEW.json`;
  SHA-256 `c194dc0530c3bea13720e02a41c02fed4a19ce1a7395d711433b83277e99dace`.
- **E2** (inputs): `n1-n6/binnacle-darwin-targeted-s-20261010/docs/darwin-investigation/native-validation/finish/results/S/SUPERVISOR-SUMMARY.md`;
  SHA-256 `82d526d55f83cd08fbb70741ace60733e113ce2b73bf51fb110d9660f9440490`.
- **E3** (repository): `src/binnacle/features/commands/job_store.py`;
  SHA-256 `be29a6335d37341486ea5ac5cdc53b43d304b8d692d0a66ee5f2d76b5a17a4d3`.
- **E4** (repository): `src/binnacle/features/commands/job_owner.py`;
  SHA-256 `b08e0505d1dd41ff1241c56a643157954a9a99729b1df20e5a91181e06f51a55`.
- **E5** (repository): `src/binnacle/features/commands/jobs.py`;
  SHA-256 `3a0d142af742600c6134d2abf4837bddeaf5e8168f44e893747285043322411f`.
- **E6** (repository): `src/binnacle/features/commands/job_resource_history.py`;
  SHA-256 `af81be5ed9a195459c9bb3df465e8c6cdebab214507adb2e6e16e3a117226c5c`.
- **E7** (inputs): `n1-n6/binnacle-darwin-targeted-s-20261010/docs/darwin-investigation/native-validation/targeted-verification/results/A/N2-OWNERSHIP.json`;
  SHA-256 `346f06e667371dda93430e9f6731adf5f6774197fd462fa33430b48dd6f38de5`.
- **E8** (inputs): `n1-n6/binnacle-darwin-targeted-s-20261010/docs/darwin-investigation/native-validation/targeted-verification/results/B/N2-API.json`;
  SHA-256 `2208d5a172f8e980b718d778e742787d1d81c5fd5bf651046587170850f06e86`.
- **E9** (repository): `src/binnacle/features/files/paths.py`;
  SHA-256 `e958060e31669172608ced4ee8c8a53ed643da1f8817e5aebddadd34db3331a8`.
- **E10** (repository): `src/binnacle/features/search/search_text_rg.py`;
  SHA-256 `1773e08e52233a42c8de0e1ad96fff6212f367f8a8ee7bafc6118624f2df637a`.
- **E11** (repository): `pyproject.toml`;
  SHA-256 `3ef33d80700da96d7be479badfc5aef55c42c7062e9d8eca246b3ff78a700517`.

R0 findings/category source (`inputs/r0/R0-REVIEW.json`):
SHA-256 `2977f84264465de10ad32915b4cccd07971db2af6ebdf584ad54d4bf965271a6`.

Repository evidence is pinned to `c2234f16bdfb1a17500b99101d3184b797ebb673`.
All historical evidence remains bounded and cannot enable this revision.

- 1.2.0 clarification (RJ1D-F3, Supervisor ACK 21:1x): close(): leaders still running when close() begins get termination_reason=owner_restart; exits observed earlier keep their Linux reason; close() returns every exit not yet released.
