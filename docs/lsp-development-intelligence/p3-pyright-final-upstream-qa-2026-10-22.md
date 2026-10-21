# Microsoft multilspy Pyright PR #168: Final cross-platform QA (2026-10-22)

The upstream Pyright contribution has been finalized and pushed, but remains
OPEN and REVIEW_REQUIRED by Microsoft. This is NOT a Binnacle production
rollout, process containment certification, or public MCP tool release.

## Provenance

- PR: https://github.com/microsoft/multilspy/pull/168
- Final contributor SHA: 7ff6e926e7fab6083ffe7233d62f9ed8d1595c09
- Parent feature implementation and coverage: 765957b; final style and
  static-analysis correction: 7ff6e92.
- Microsoft multilspy baseline v0.1.1 (62acb3cf2d7a0746992ca08767d8a4fded402ebb).
- Real Pyright version: 1.1.413, using pyright-langserver --stdio.
- The user-authorized Fable 5.1 run completed with no imposed spending cap.
  Its implementation and reports were independently verified on both hosts.

## Native final QA matrix

All six runs exercised the exact same verified candidate bytes (file hashes
and patch content matched), including real Pyright, inherited Jedi behavior,
LSP completion, diagnostics, startup/failure tests and sync APIs.

| Host | CPython | Focused suite |
| --- | --- | --- |
| MacBook Pro, macOS ARM64 | 3.10.22 | 77/77 passed |
| MacBook Pro, macOS ARM64 | 3.13.16 | 77/77 passed |
| MacBook Pro, macOS ARM64 | 3.14.8 | 77/77 passed |
| Raspberry Pi, Linux ARM64 | 3.10.21 | 77/77 passed |
| Raspberry Pi, Linux ARM64 | 3.13.16 | 77/77 passed |
| Raspberry Pi, Linux ARM64 | 3.14.7 | 77/77 passed |

Additional acceptance gates: targeted Ruff check passed; Python compileall
passed; git diff --check passed; wheel built with PyrightServer and its
initialize_params.json; test sources unchanged and no regular Binnacle
service restarted. Temporary commit/push hooks prevented further commits
until final QA, permitted one final verified commit/push and were reclosed.

The GitHub fork branch and Microsoft PR head both subsequently resolved
to SHA 7ff6e926e7fab6083ffe7233d62f9ed8d1595c09. The PR description
now includes the tested SHA, platform/version matrix, and capability/gap table.

## What the upstream contribution covers

The tests exercise Pyright's actual initialize capability response plus
real definitions/references/hover, completions and completion resolution,
document/workspace symbols, declaration/type-definition, signature help,
document highlights, incoming/outgoing call hierarchy, rename previews
and diagnostics. Rename/edit responses were not applied to project files.
Off/basic/standard/strict Python type-checking settings were checked on
isolated projects.

The following gaps remain **intentionally not described as fully supported**:

- This Pyright version did not advertise implementationProvider, pull
  diagnosticProvider, or several other optional LSP methods. They cannot
  be claimed from the protocol specification alone.
- Code actions requiring third-party type-stub generation lack a safe
  deterministic read-only fixture and may write files.
- executeCommand may mutate files. The adapter intentionally refuses
  server-initiated edits; this is a safety restriction, not full command
  execution support.
- Pyright real-provider tests remain opt-in through
  MULTILSPY_PYRIGHT_TEST_BINARY. The upstream contributor account lacks
  GitHub workflow-edit scope; do not claim Microsoft-hosted CI ran these
  native tests.
- Microsoft has not yet merged PR #168 or released these changes. Official
  multilspy v0.1.1 alone does NOT include the new behavior.

## Next Binnacle tasks

Continue P2.4 Linux/macOS process ownership and P2.5 authorized
workspace/URI/document snapshot handling, followed by P2.6 manager and
P2.7 conditional MCP mounting. Pyright provider security and READ
classification remain separate release gates. No Binnacle production
code was changed in this final upstream QA.
