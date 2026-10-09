# Development infrastructure independent audit and implementation receipt

Reviewed: 2026-10-09. Production source baseline:
`045ff9eea07b301cea849b69f99e87704ab1b155`.

## Verified issues and fixes

- **Coverage false-green**: before this change, a report listing only nine
  `src/binnacle` modules could pass the per-module checker even though the
  repository had 122 substantive modules. The gate now loads the current
  source inventory, rejects missing/stale paths, rejects empty/malformed
  inventory and invalid nonfinite percentages, and preserves final 95/90
  thresholds. Negative fixtures prove the failure paths.
- **Mutation false-green**: before this change, one tested mutant out of
  ten in a timed-out run could yield an `ok` module check. Incomplete,
  timed-out, empty and partial results now WARN. Rotation advances only
  when all selected modules were fully checked, leaving unfinished modules
  due for the next eligible quiet-window attempt.
- **CI credentials**: every read-only `actions/checkout` step has
  `persist-credentials: false`. GitHub permissions remain `contents: read`.
- **Dependabot supply-chain**: all three configured ecosystems use a
  seven-day release cooldown for routine version updates. Dependabot security
  updates remain immediate. The config was reviewed using the current
  official GitHub cooldown specification.
- **zizmor**: add pinned `zizmor==1.30.1` to the locked lint toolchain;
  pre-commit `zizmor` audits workflows, Dependabot and hook config offline,
  requiring zero medium+ findings. Before remediation the audit emitted
  five missing checkout-credentials controls and three cooldown findings.
  After remediation the baseline has no unsuppressed findings.
- **Script-test confidence**: `scripts/` is now captured in the existing
  coverage run without executing pytest twice. The checker requires all
  46 top-level non-initializer scripts in the full report and individually
  enforces reviewed coverage minimums on twelve critical quality, security
  and deployment scripts. Script-only seeded coverage pilot used
  `tests/scripts`: 542 passed, 46 substantive scripts measured, zero
  below their initial reviewed floors. The three critical scripts below the
  eventual 90% target are `check_architecture` (83.15%),
  `check_coverage_policy` (73.79%) and `github_governance` (52.31%).
  Low initial floors are explicitly identified as debt, not advertised as
  a 90% success.
- **CI diagnostics**: each of the two ordinary test-suite lanes emits its
  own opt-in JUnit XML file. The four coverage lanes do likewise. GitHub
  collects only failed test and coverage job artifacts, each with a unique
  attempt-scoped name and seven-day retention, and prints 15 slowest tests.
  The seven check identifiers, matrix, public API, smoke and deployment gates
  are unchanged.
- **CodeQL**: plan to enable GitHub default CodeQL scanning for Python and
  Actions after the exact candidate has passed existing CI; leave separate,
  non-required until scanner reliability is independently assessed.
- **Other tools**: a standalone Pyright trial reported eight errors, mostly
  Pydantic typing differences from MyPy's plugin, with one potentially
  unbound variable. Experimental Ruff families yielded 28 findings,
  and Vulture 8 100%-confidence unused-parameter warnings linked to callbacks
  and protocol hooks. None is made a blocking default before false positives
  are investigated.

## Boundaries and known measurement details

- Source tests remain the canonical `pytest -m not no_xdist` and ordinary
  `pytest -m no_xdist` lanes with fixed seed 12345 on ordinary CI; stress,
  mutation and multiple random seeds remain isolated in weekly scheduled
  quality jobs.
- `coverage.py`'s `percent_covered` with branch tracking enabled is a
  *combined statement-and-branch percentage*, not the arithmetic fraction
  of covered branches alone. This preserves the documented historical
  `coverage.py` policy baseline; changing the metric definition is a separate
  governance decision, not an implicit test gate reduction.
- No runtime code, public MCP surface, tool ordering, CLI, service or
  durable-job protocol changes were authorized or made.
- This receipt is a local source/design record, not proof of a finished
  deployment. Exact CI, local full suite, CodeQL state, live smoke and user
  file integrity must be verified and recorded separately.

## Verification ledger (before final candidate freeze)

- Initial security pilot: eight medium zizmor findings (five checkout, three
  cooldown); after fixes no unsuppressed findings.
- Targeted tests after integration: 76 passed.
- The first branch-enabled script-coverage end-to-end candidate revealed one
  test-infrastructure timeout in the seven-case Gate A negative test. That
  test recomputed the unchanged complete AST/G7 scan on every case under
  instrumentation. Cached the unchanged source-import findings in the test
  and delegated the full G7 gate to its independent tests; the exact failing
  case reran with script coverage and passed in 5.24 seconds without raising
  pytest's 60-second timeout. The first timed-out pipeline is not a pass.
- `pre-commit run --all-files`: all hooks passed, including Gitleaks,
  Actionlint, Ruff, MyPy, Deptry, new zizmor, architecture and legacy gates.
- Synchronous `uv lock` / `uv sync --locked --group dev` succeeded with
  pinned `zizmor` and PyYAML typing support.
- Pending release evidence: one frozen full suite, one complete coverage
  pipeline, packaging smoke, all seven exact-SHA GitHub checks, guarded deploy
  smoke, CodeQL setup status, and user source checksum preservation.
