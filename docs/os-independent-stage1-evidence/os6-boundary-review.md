# OS6 source-boundary reconciliation

Status: candidate source sweep performed; **independent review is pending**.
Task: BINNACLE-OS-STAGE1-IMPLEMENT-20261009.

The full per-file report is `os6-source-reconciliation.json` and is generated
by `uv run python -m scripts.os_stage1_inventory`. It includes each Python
source under `src/binnacle` and `scripts` with path, SHA-256, imports,
KEEP/BOUNDARY/LINUX owner, concrete rationale, stage, and baseline membership.

## Results before final CI

| Check | Result |
| --- | --- |
| Initial production modules | 143 |
| Current production modules | 152 |
| Current Python scripts | 49 |
| Ownership classification | KEEP 122; BOUNDARY 20; LINUX 59 |
| Newly introduced source paths | 11 |
| Baseline Python source paths removed | 0 |
| Static architecture violations | 0 |
| FastMCP Provider/registry shadow | 0 observed in source |
| Native root and mounted children | One root, three mounts |
| Public tool ownership | Eight distinct raw tools |
| Unknown OS fallback to Linux | Forbidden |

New Linux modules include verified job pidfd identity, native
systemd notification and Linux unit inspection. The new OS-independent
modules are the FastMCP composition root, generic stop policy and narrow
provisioning/identity contracts. Existing Linux-only Watchdog/Tunnel and
maintenance scripts remain explicitly classified rather than pretended to
be portable. The legacy `job_platform` and `deployment_platform` facades
remain for supported imports; no unsupported facade was deleted.

The canonical-root authority fix retains original aliases but freezes their
resolved set for a single application generation. Repointing a configured
symlink alone no longer grants different directories. This does not solve
filesystem time-of-check/time-of-use races involving the canonical
ancestor's own replacement; see the architecture document. The existing
path APIs are not a security sandbox against arbitrary same-user shell
access.

## Evidence and outstanding independent work

- `tests/scripts/test_os_stage1_native_boundaries.py` tests the direct
  Core-to-companion prohibition, absence of FastMCP imports in platform
  protocols/adapters, one application factory and three mounts.
- `tests/scripts/test_os_stage1_inventory.py` validates complete
  enumeration, classification and positive/negative ownership cases.
- `tests/contracts/test_os_stage1_wire_parity.py` checks exact v1.0.1
  client wire and raw Provider multiplicity, not new goldens.
- Existing `scripts/check_architecture.py` and `lint-imports` enforce
  native adapter boundaries with tests for direct, aliases and literal
  dynamic imports. Portability claims remain **Linux-only**.
- The source-bound review still needs a genuinely independent reviewer,
  bound to the final exact candidate commit and diff. Authored or
  self-generated review packets are evidence inputs, **not approvals**.

The file manifest must be regenerated after any further production change.
Only a clean normal Git commit with intact hooks, trusted CI and independent
review can authorize a production candidate; an active Job Manager is a
separate guarded rollout decision.
