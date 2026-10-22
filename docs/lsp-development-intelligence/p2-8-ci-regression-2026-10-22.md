# P2.8 — full CI and release-gate regression acceptance

Date: 2026-10-22 (Australia/Sydney). Baseline `eead659481fcadce2edd2036cb13b0b088d56c50`
(P2.7). Candidate: private isolated `feat/lsp-p28-ci-release-20261022`.
This is a **quality-repair candidate**, not a production deployment or public
`inspect_symbol` release. In particular, it does **not** supersede the P3
filesystem/OS containment and P4/P5 tool-release decisions.

## Failed baseline; evidence-guided diagnosis

Binnacle P2.7 hosted [Actions 39715546427](https://github.com/grammy-jiang/binnacle/actions/runs/39715546427)
reported Packaging PASS, Code Quality FAIL and Coverage FAIL, with the test
matrix cancelled by job fail-fast. The earlier P2.6 full Linux run showed
27 failures despite private native P2.6 and P2.7 success:

- **Environment/optional extra:** default `tox` sync installed neither
  multilspy nor psutil, although P2.4 real-provider and native process-tree
  tests require both. This is not evidence of a Pyright defect.
- **Frozen inventories:** `config_development_intelligence` and Darwin's
  maintenance fence entered the manager import closure without a corresponding
  pinned name; the G6 ownership report did not classify 18 Development
  Intelligence modules and the new config module.
- **Quality:** old LSP review documentation used bare links or malformed
  Markdown; one typo fixture and a Ruff nested-context test failed. Several
  temporary archival scripts used valid direct-CLI imports that were not
  understood as first party by Deptry and had ambiguous branches to mypy.
  `typing_extensions` was imported directly but not declared as direct.
- **False-platform assumptions in test fixtures:** several otherwise native
  POSIX tests skipped an entire module, violating the strict policy; the
  historical Codex fixture used a MacBook MCP tool name while resolving the
  server name from a Linux test host. Neither is a product runtime defect.
- **Coverage job:** failed during its *test execution*, initially before the
  final coverage report/threshold evaluation. Do not misstate that failure as
  actual measured coverage below the gate.

## Implemented corrections — without reducing quality policy

1. `tox`'s **test/coverage environments** explicitly install the separately
   declared `development-intelligence-pyright` extra. The **Code Quality CI
   job** also explicitly syncs that locked extra for third-party typing. The
   ordinary runtime/default wheel still installs **neither multilspy nor
   psutil**. P2.4 uses the upstream pinned multilspy Pyright implementation,
   not an adapter reintroduced into Binnacle.
2. The manager import graph pins inert schema and Darwin fence modules, with
   actual startup set negative/positive tests intact. G6 explicitly assigns
   all 18 Development Intelligence Python modules to a reviewed owner;
   no broad wildcard allows unexpected files. Automatic server startup
   inventory remains generated and checked.
3. Preserved *all* repository-wide Linux and Darwin mypy gates. Script
   direct-CLI imports are typed via `TYPE_CHECKING`; fixture peers and process
   snapshots now type-check without hiding whole files. The narrow
   `# type: ignore[import-untyped]` comments cover only the upstream fork's
   optional, presently untyped modules. The separate TYPE-01 positive/negative
   controls remain fully enforced. Added direct `typing-extensions` and lint
   `types-psutil` dependency evidence.
4. Existing platform-skip contract remains strict. POSIX-only unit/integration
   tests now own **individual** approved platform marks instead of an entire
   module skip; all new mark locations and counts were explicitly ratcheted.
   Historic synthetic MCP identity tests use the fixture's explicit Mac target,
   rather than changing the production host-detection policy.
5. Real `lsof` can report incomplete namespace filesystem enumeration in
   container environments. **Production `classify_lsof_census` is unchanged**
   and correctly rejects any nonempty stderr, even with exit code zero.
   A test of this circumstance first proves the rejection, then marks the
   *positive* FD-observation test unsupported on that host; it never strips
   warnings, suppresses stderr or claims a clean/authorized file census.
   Native Raspberry Pi POSIX tests continue to exercise the four positive
   cases when its `lsof` produces complete evidence.
6. Ruff, Bandit, Markdownlint, Codespell, Deptry and architecture fixes were
   made at exact sources; no global ignore or lower branch-coverage target.
   LSP wire decoder now checks body-length invariant even under Python `-O`
   instead of relying on an optimizable `assert`.

## Native evidence (isolated candidate source)

- **macOS arm64 Python 3.13:** 163 P2.4–P2.7 native real-Pyright tests PASSED.
- **macOS arm64 Python 3.10:** 64 selected P2.7/P2.8 regression cases PASSED;
  one `tomllib` contract test correctly skipped (stdlib since 3.11).
- **macOS arm64 Python 3.14:** 67 selected P2.7/P2.8 cases PASSED.
- **Linux ARM64 Raspberry Pi Python 3.13:** full CI-style `tox -e py313`
  initially PASSED (7,858 parallel-safe and 98 ordinary). With all 91 P2.8
  coverage tests included, the **final verified candidate PASSED 7,949
  parallel-safe tests (339 skipped, 87 subtests) plus 98 ordinary-process
  tests: 8,047 passed in total, zero failed**. Four actual `lsof` positive
  controls remained PASS when the host census was complete.
- **Entire checked repository (Mac):** 897 Python files passed mypy for both
  Linux/Darwin targets. `pre-commit run --all-files` PASSED every configured
  quality hook, including TYPE-01; separate gitleaks Git-history hook PASSED.
  Default-off runtime had neither optional provider package. No-extra wheel
  smoke test PASSED. Lock validation, startup inventory, architecture and
  strict module-size gates also PASSED.
- **Linux ARM64 Sextant Python 3.13:** after an initial warning-host `lsof`
  census failure was corrected in the test fixture (without changing runtime
  refusal policy), the next run reached the coverage threshold and identified
  11 low-coverage Development Intelligence modules. The final run including
  91 additional synthetic fault/boundary cases PASSED **Coverage Policy with
  zero enforceable errors**, without any coverage target/floor changes. It
  executed 3,341 unit parallel-safe tests, one unit ordinary-process test,
  4,603 nonunit parallel-safe tests and 97 nonunit ordinary-process tests, with
  all four lanes successful. Incomplete `lsof` observations remain correctly
  rejected and only the corresponding positive controls are skipped on this
  containerized host.

All three candidate checkouts originally held the exact same binary Git diff
from the P2.7 baseline. The additional narrowly scoped `lsof` fixture change
was replicated and verified by source SHA. All tests operate on temporary
synthetic projects; no Binnacle production manager, MCP server or GitHub
upstream multilspy PR service was changed or restarted.

## Coverage Policy remediation: real source-path and failure branches

The second complete Coverage Policy run, before the added tests, executed all
unit and nonunit lanes successfully and then reported **11 enforceable
per-module failures** in Development Intelligence. No coverage floor or target
was changed; the failing module list was read from its real `.tox/coverage-full.json`
report, not estimated from passing focused tests.

Seven new exact-purpose regression modules now add **91 cases** across native
process ownership, workspace descriptor I/O failures, LSP JSON-RPC client
malformed/timeout paths, document synchronization, bounded resident manager
queues and shutdown, private FastMCP child lifecycle, and one-shot workspace
admission. They do not introduce another Pyright Adapter, signal any real PID
or declare untrusted filesystem confinement proved. The existing real Pyright
integration tests remain independent.

**Final measured per-module *full* branch coverage** from Sextant's
`.tox/coverage-full.json`, after every unit/nonunit lane completed:

| Development Intelligence module | Previous full CI | Final full CI-style measurement |
| --- | ---: | ---: |
| `lsp_authorized_session.py` | 60.00% | **100.00%** |
| `lsp_client.py` | 85.02% | **97.38%** |
| `lsp_document_sync.py` | 89.17% | **97.92%** |
| `lsp_manager_cooldown.py` | 80.00% | **100.00%** |
| `lsp_manager_shutdown.py` | 87.50% | **98.44%** |
| `lsp_policy.py` | 88.46% | **100.00%** |
| `lsp_preview_server.py` | 89.91% | **98.17%** |
| `lsp_process_owner.py` | 80.10% | **98.43%** |
| `lsp_provider_manager.py` | 89.89% | **92.02%** |
| `lsp_wire.py` | 89.68% | **96.13%** |
| `lsp_workspace_access.py` | 75.40% | **92.33%** |

**11/11 enforceable Development Intelligence modules now exceed 90%**. The
coverage validator checked 255 production modules and 67 script modules,
reported **zero enforceable errors**, and retained **20 unrelated, already
approved temporary-floor debts** below the eventual 90% target. We have not
changed `quality-policy.json`, deleted tests or misclassified a skip as a pass.

Local Mac Python 3.10, 3.11, 3.12, 3.13 and 3.14 each passed **91/91** new
cases; both Linux Pis passed the identical SHA-256-verified 91/91 suite. The
full repository Linux/Darwin mypy checks **897 Python sources** with zero
errors; GitHub-configured local pre-commit hooks and the manual Git-history
secret scan passed with the seven new tests included in the staged-intent
file inventory.

The P2.5 dedicated adversarial TOCTOU corpus that the execution environment
previously blocked has **not** been executed or credited: synthetic I/O fault
injection is valuable branch coverage but not an OS sandbox proof. This safety
gate stays OPEN in P3.

## Remaining gates (do not close early)

- **Local Coverage Policy and full Python 3.13 tox acceptance are PASS.**
  The next mandatory check is the hosted GitHub Actions run on the final
  committed source; local success must not be reported as hosted success.
- Finalize one coherent P2.8 commit/branch and verify hosted
  GitHub Actions Python 3.10, 3.11, 3.12, 3.14, Code Quality, Coverage Policy,
  Packaging and the manual Git-history secret gate. A local pass is not
  evidence that hosted CI passed.
- Preserve P2.5 dedicated adversarial TOCTOU review and P3 OS/Pyright write
  side-effect/security classification as independent **NO-GO** public release
  conditions. The P2.7 private QA tool is not an approved MCP product API.
