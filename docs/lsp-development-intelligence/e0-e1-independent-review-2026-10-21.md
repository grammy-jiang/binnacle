# E0/E1 independent review trail — 2026-10-21

**Final disposition: GO — local anonymous opportunity-metadata analysis only.**
This does not approve task-level efficiency claims, public LSP tools, production
provider execution or retrospective replay of raw user instructions.

All review rounds used an ephemeral read-only Codex reviewer scoped to
synthetic source and tests. The reviewer was explicitly prohibited from
opening private full-capture logs, local session databases or user configs,
and made no repository edits.

| Independent review round | Verdict | Concrete finding and handling |
| --- | --- | --- |
| Initial reliability review | REWORK E0/E1 | Eight defects: false request pairing, unpaired sequence participation, ambiguous observer alternatives, malformed/Unicode payload errors, UTC parsing, terminal order, timestamp/failure chronology, overbroad lexical classification. Repaired with synthetic regressions. |
| First follow-up | E0 GO / E1 REWORK | A negative-duration terminal retained its nonzero exit code and manufactured a failed-test follow-up window. Invalid chronology now excludes the entire call from confident sequence evidence. |
| Second follow-up | E0/E1 GO for original cases | Verified original eight findings and negative chronology without reading actual logs. |
| Refactor/frozen-cohort audit | REWORK for one case | Under an exclusive cutoff, a tool_call with an unknown timestamp was discarded before its request group could be marked unorderable, compressing bounded action windows. |
| Final targeted follow-up | GO | Unknown-timestamp tool calls now mark group uncertainty before cutoff exclusion. Both five-call and ten-call negative tests run with and without a cutoff and reject manufactured opportunities. No new private-data disclosure observed. |

## Implementation and execution evidence

- Primary reviewed implementation commit: f060b14 (isolated LSP branch).
- Authored modules: scripts/lsp_e01_trace.py, scripts/lsp_e01_patterns.py,
  scripts/lsp_e01_observer.py. All below the 500-line hard limit.
- Deterministic synthetic suite: **45 passed on MacBook Pro, 45 passed on
  Raspberry Pi, 45 passed on Sextant** for the final code snapshot.
- MacBook E0/E1 suite also passed on both **Python 3.10 and 3.14**. The
  existing LSP P1 regression suite remained **373 passed**.
- The final six-file synthetic-only transfer bundle was verified locally
  on each Pi using SHA-256:
  139a843553e5eda4d3e586b0819b9ca9617cc5672a7193f6c5258d9d55d6bf35.
  The code ran from temporary directories, not deployed Binnacle directories.
- Ruff, formatting, architecture analysis, import linter, startup import
  inventory and selected existing MCP tool-surface contracts passed. The full
  repository CI/coverage-policy gates were not executed for this offline pilot.

## Remaining limitations

A request group does not equal a development task, and a timestamped tool
sequence does not prove one model reasoning step was avoided. Shell command
classifiers are lexical, incomplete historical eras remain scrubbed, and
uncommitted repository state/user prompt/model token accounting is missing.
No original historical command is executed during extraction. E2 must
separately validate candidate cases and report non-replayable exclusions;
later controlled agent A/B is the only valid path to tool-benefit claims.
