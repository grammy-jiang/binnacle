# P3.5 — Opt-in capability and resource benchmark harness

Baseline: `66697d280cc2`, isolated branch
`feat/lsp-p35-benchmarks-20261022`. Date: 2026-10-22.

**Implementation evidence only. READ remains NO-GO.** Pyright remains
`explicit_trust_only`. A correct, fast response does not establish confinement,
public-tool value, or permission to deploy. Authoritative medium, concurrent,
and resident-instance timings remain deferred until the host is quiet.

## Implementation and boundary

Run `python -m scripts.lsp_benchmark`. Imports are inert. `--run` explicitly
admits an experiment. The CLI requires a preinstalled absolute Pyright executable;
it never downloads a provider or searches for one. The supported npm layout must
report Pyright 1.1.413. The installed multilspy VCS metadata must identify
`08ba0dbe60b6e0a3eff4796cb77ff5c0837bc892` for the integrated P3.3–P3.6 candidate. The retained 2026-10-22 bounded-smoke JSON was produced on historical `9203732e4e5f65cc1374b109110f7b6354d3d43b` and remains an immutable, non-authoritative baseline; it is NOT evidence for the updated pin.

The harness uses the existing P2.6 manager, P2.5 document synchronization, P2.4
process owner, and upstream multilspy PyrightServer. The owner factory wraps the
upstream initialize call only to observe duration and negotiated capabilities.
It does not implement transport, lifecycle, initialization settings, or another
provider adapter. No production module, service, public MCP registration, tool
schema, or dependency lock changes are needed.

Six operation rows have gold assertions:

| Operation | Execution path | Correctness check |
| --- | --- | --- |
| Manager definition | P2.6 → P2.5 → upstream | Exact file and complete UTF-16 range |
| Definition | Direct upstream on the same owned resident | Exact location set |
| References | Direct upstream, declaration included | Complete three-location set on synthetic corpus |
| Hover | Direct upstream | Expected symbol and typed parameter text |
| Document symbols | Direct upstream | Expected name and selection range |
| Workspace symbols | Direct upstream | Expected name and location |

Every direct operation checks the negotiated capability before dispatch. Missing
capabilities produce `unsupported`, not a successful empty answer. All-unsupported
runs are invalid. Supported but incorrect results invalidate their budget labels.
These direct calls are private measurement probes on immutable disposable copies.
They are not authorized-document APIs for untrusted callers.

The direct and manager requests share a resident process but run in separate
blocks. **Do not subtract their percentiles to claim Binnacle-only overhead.**
This is not the independent raw-LSP Suite A or the FastMCP/HTTP Suite B. P4.6 still
owns paired decomposition and workflow A/B. Push diagnostics, completion, rename,
call hierarchy, editing, and execute-command benchmarks are outside this harness.
Existing P3 feature acceptance does not become P3.5 timing evidence for those calls.

## Reproducible commands

Create the local locked environment, without global dependencies:

```bash
UV_CACHE_DIR=/tmp/binnacle-p35-uv uv sync --locked --group dev \
  --extra development-intelligence-pyright
```

A tiny functional smoke needs no quiet-host attestation. It permits only the
small corpus, one instance, concurrency one, one warm-up, at most three measured
requests per operation, and a workload budget of at most 45 seconds:

```bash
.venv/bin/python -m scripts.lsp_benchmark --run \
  --binary /absolute/trusted/pyright-langserver \
  --scale small --warmup 1 --repeats 1 --total-s 40 \
  --output /tmp/p35-small-smoke.json
```

After independently confirming that no other agents or competing workloads are
active, use `--quiet-host` to attest that condition. The flag is an operator
attestation, not automatic detection or permission to interrupt other work:

```bash
.venv/bin/python -m scripts.lsp_benchmark --run --quiet-host \
  --binary /absolute/trusted/pyright-langserver \
  --scale medium --warmup 3 --repeats 100 \
  --concurrency 2 --instances 2 --total-s 180 --deadline-s 15 \
  --sample-interval-s 0.1 --p95-budget-ms 100 --rss-budget-mib 512 \
  --output /tmp/p35-medium-two-residents.json
```

Run small and medium separately. Repeat each command with new output filenames
for independent cold starts. Output files use exclusive creation; existing files
are never overwritten. The runner creates temporary roots and deletes only those
roots after owned process cleanup. It does not initialize Git or execute corpus
Git commands.

The small fixture contains two Python files and fixed Pyright configuration.
The medium fixture adds 128 linked modules with 16 functions each: 130 Python
files, 131 files total. Both use generator revision `p35-python-v1`. File-content
and gold hashes identify the exact corpus. This controlled corpus is not a claim
of real repository representativeness.

## Optional real corpus: explicit trust and source snapshots

No real corpus was authorized or ingested during this implementation. Supplying
`--real-root` alone is denied before reading its files. A real run requires all
three flags and `--quiet-host`:

```bash
.venv/bin/python -m scripts.lsp_benchmark --run --quiet-host \
  --binary /absolute/trusted/pyright-langserver \
  --real-root /absolute/reviewed/repository \
  --trust-real-workspace /absolute/reviewed/repository \
  --real-manifest /absolute/reviewed/corpus-manifest.json \
  --warmup 3 --repeats 30 --output /tmp/p35-trusted-snapshot.json
```

The manifest is operator-reviewed local input. Example shape, with placeholders
that must be replaced with actual reviewed hashes and gold positions:

```json
{
  "schema": 1,
  "revision": "<40 lowercase hexadecimal Git commit characters>",
  "files": {"lib.py": "<SHA-256 of the reviewed bytes>"},
  "cases": [
    {
      "operation": "manager_definition",
      "file": "lib.py",
      "line": 0,
      "character": 4,
      "symbol": "greet",
      "locations": [["lib.py", 0, 4, 0, 9]]
    }
  ]
}
```

Only explicitly listed regular `.py` files are copied. No repository traversal,
project configuration, executable, `.git` data, or symlink ingestion is allowed.
Limits are 256 files, 1 MiB per file, 8 MiB total, 32 cases, and a 256 KiB manifest.
The provider runs on a disposable copy with the harness's fixed configuration.
The Git revision is **operator-declared**; file hashes are verified. The harness
does not claim the source worktree is clean or identical to that Git revision.
This source-subset corpus is not a full repository indexing measurement.

Case anchors are zero-based Python codepoint offsets. Direct requests convert
them to UTF-16. Gold locations are `[file, start_line, start_utf16,
end_line, end_utf16]`. Hover and symbol cases also supply `names`, containing
expected text fragments or symbol names. The first case must be a manager
definition, which initializes the resident through the existing admission path.

This is explicit operator trust, not hostile filesystem race protection or an OS
sandbox. P3.3 confinement restrictions still apply. No performance flag can
promote a provider to `audited_read_eligible`. The original sources are never
passed as the provider workspace and are never intentionally written.

## Measurement semantics and JSON contract

The aggregate JSON schema identifier is `binnacle.p35/1`.

- Startup-to-first-result includes manager admission, process startup,
  initialization, document synchronization, and the first definition response.
  Initialize-response timing separately covers the initialize RPC only.
  Teardown covers bounded manager/owner shutdown.
- Each supported instance receives exactly `warmup` settling calls and exactly
  `repeats` measured calls per case. Resident reuse is checked against initialization counts. A replacement
  resident invalidates the warm-run evidence.
  Failed warm-up correctness prevents a passing operation budget label.
- Response latency ends when the awaited query returns, before gold checking or
  JSON size calculation. It includes harness scheduling and the per-instance
  serialization queue. Concurrency is bounded to four tasks; instances to three.
  Same-instance operations serialize. Separate instances can run concurrently.
- Percentiles use nearest rank: sorted index `ceil(p * n) - 1`. JSON includes
  sample counts, p50/p95/p99 for all measured responses and correct responses,
  correctness/error/timeout rates, result counts, and encoded result byte sizes.
  Empty sample sets use null percentiles. Fewer than 30 repeats are `smoke`;
  30–99 are `exploratory`; 100 or more are `repeat_candidate`.
- A workload has a total deadline; each request also has a deadline. Cleanup
  retains P2.4/P2.6's own finite deadlines after workload expiration. The total
  flag is not a hard process-kill deadline that bypasses cleanup.
- psutil samples owned roots and recursive children at the requested interval
  and phase boundaries. JSON records sampled tree RSS peak, resident tree RSS
  peak, maximum observed resident/process counts, cumulative observed CPU time,
  observation counts/errors, and harness process CPU time.
- RSS sums may double-count shared pages. Sampled peaks are lower bounds.
  Short-lived or escaped children can be missed. CPU totals retain each observed
  PID/birth identity's highest counter. These are observations, not hard memory
  quotas, idle CPU measurements, whole-host accounting, or containment proof.
- Resource budgets and latency budgets are explicitly provisional. Labels are
  `within_provisional_budget`, `exceeds_provisional_budget`, `unsupported`,
  `invalid_correctness_or_incomplete`, or `unobserved` as applicable. Exceeding
  a budget does not erase a correct result. CLI exit 0 means a complete,
  correct supported run with verified cleanup and unchanged snapshot; exit 2
  means unavailable, denied, incomplete, or invalid. Inspect budget labels
  separately. Resource observation failure is not a zero-memory result.
- Environment records OS/release, architecture, Python, CPU count, load averages,
  source revision/dirty state, harness and lock hashes, Node version/executable
  hash, Pyright launcher/package/bundle hashes, upstream SHA, and initialize
  template hash. Digests are provenance observations, not package signatures.
- Exported data contains no source text, corpus file names, absolute paths,
  URIs, environment variable values, provider diagnostics, or exception text.
  Commands use a redacted executable placeholder. Raw stderr/log output is
  suppressed. This sanitized aggregate does not preserve raw payloads for replay.

`valid` describes the requested supported correctness experiment, not READ safety
or release approval. `authoritative_timings` remains false. Soak, post-idle,
eviction/RSS recovery, independently reviewed correctness, and P3.6 resource
policy still require separate evidence.

## Future P3.4 profiles

The runner consumes a backend with `start`, `supports`, `query`, `processes`,
`residents`, `initialization`, `roots`, and `close`. Gold cases and measurement
logic are independent of native process construction. A future admitted profile
can supply that interface using its existing owner/upstream adapter and a
versioned corpus. Extend reviewed gold validators for different result shapes.
Do not implement another language-server adapter in this harness.

Candidate CLI labels for TS, clangd, Rust, Marksman, Bash, Makefile, YAML, and JSON
currently return `profile_not_admitted` without executable discovery or launch.
This baseline has no P3.4 launch grants. Missing Pyright returns `not_installed`;
an installed wrong version or wrong upstream provenance fails admission.

## Validation and current limits

The deterministic suite uses injected backends and resource samples. It covers
exact repetitions, concurrency, gold ranges, false/empty responses, unsupported
capabilities, request timeouts, cancellation cleanup, resource aggregation,
provenance mismatch, real-root trust, hashes, traversal/symlinks, denied project
configuration, output sanitization, and overwrite refusal.

```bash
.venv/bin/pytest -q tests/scripts/test_lsp_p35_benchmark.py \
  tests/integration/test_lsp_p35_native_benchmark.py

BINNACLE_P35_NATIVE_SMOKE=1 \
PYRIGHT_LSP_TEST_BIN=/absolute/trusted/pyright-langserver \
.venv/bin/pytest -q tests/integration/test_lsp_p35_native_benchmark.py
```

The native test skips by default. Explicit runs use the actual pinned upstream
and Pyright process, verify gold results, resource observations, unchanged
snapshot, and cleanup. An installed but incompatible provider fails the smoke.

The environment doctor initially found a missing local virtual environment and
missing shared pre-commit/pre-push hooks. The local environment was synchronized;
shared hooks were not installed or changed. `codex-usage-guard` was not on PATH.
No manager, service restart, commit, push, rebase, or deployment was performed.

## Bounded native evidence

[Sanitized aggregate JSON](p3-5-bounded-smoke-2026-10-22.json) records the final
six-operation CLI smoke on Linux aarch64, Python 3.13.16, Pyright 1.1.413, and the
pinned upstream. It used one instance, concurrency one, one settling call and
one measured call per operation. All **6/6 settling and 6/6 measured gold checks
passed**, with zero request errors/timeouts. Cleanup was verified and the
complete disposable file/directory snapshot remained unchanged.

Observed startup-to-first-result was **2981.83 ms**, initialize RPC **530.04 ms**,
and teardown **703.25 ms**. The sampled process-tree peak was **168,083,456 bytes**,
with two observed processes and one resident instance. There were 34 samples,
zero sampling errors, and **2.50 seconds** of observed process CPU time.
Resident reuse was verified.

| Operation | Single measured response (ms) |
| --- | ---: |
| manager_definition | 6.958 |
| definition | 1.875 |
| references | 5.385 |
| hover | 2.245 |
| document_symbols | 1.928 |
| workspace_symbols | 1.421 |

**Sample size is one per operation.** Each percentile therefore equals its one
sample. These observations are functional smoke evidence, not a latency baseline
or performance ranking. The host was not attested quiet; other development work
and local validation were present. Do not use these numbers to choose TTLs,
instance limits, production deadlines, or release readiness.

## Validation record and remaining work

- New deterministic suite: **49 passed**, optional native test **1 skipped**
  without opt-in. Separate CLI native smoke: **6/6 operation rows passed**.
- Final combined P3.5, P2.5/P2.6/P3.1, and composition selection:
  **145 passed with 1 optional native skip** on the final selection. The native
  CLI smoke separately exercised the final harness. The preceding combined
  run with the native test enabled also passed all 145 then-existing cases.
- Composition contracts: **26 passed** with
  `BINNACLE_TELEMETRY__FULL_CAPTURE__DIRECTORY=/tmp/binnacle-p35-test-capture`.
  The first run inherited host full-capture configuration whose directory was
  read-only in this sandbox; it failed. A separate contract-only run reproduced
  that failure. Redirecting the configured capture directory to disposable
  storage fixed it without changing production code or disabling capture.
- Targeted Ruff, mypy, and Bandit passed. OS6 regenerated/check passed:
  **281 production modules, 74 scripts, zero architecture violations**.
  Architecture and generated startup-module checks passed.
- The first pre-commit bootstrap hit a read-only default npm cache. Redirecting
  npm, Go, uv, and pre-commit caches to `/tmp` resolved setup. The first complete
  gate found one new mypy `SimplePath` conversion error; it was corrected.
- Repository `pre-commit run --all-files` passed after the type correction.
  All new-file pre-commit checks also passed, including full Linux/Darwin mypy,
  Ruff, Bandit, module size, Markdown, secrets, and dependency checks.
- Full pre-push, coverage-policy, Python matrix, soak, medium corpus, multi-instance
  native runs, and real-workspace runs remain unexecuted in this session.
  No authoritative timings, independent security review, or release GO is claimed.

The generated OS6 reconciliation file includes accumulated baseline drift as
well as the six new harness modules. It is generated evidence, not a change to
production behavior. P3.6 must wait for quiet-host representative measurements;
P3.3 and P4/P5 remain independent gates.

## Cross-platform readiness correction — 2026-10-23

macOS arm64 Pyright 1.1.413 returned an empty `workspace/symbol` response
on its first query after the first successful definition; the second query
returned the exact reviewed symbol and location. The raw response was tested
in disposable synthetic sources, and no user repository was read. The private
P3.5 harness now performs a bounded, gold-checked workspace-symbol readiness
preflight (up to five seconds) before *measured* warm calls, recording its
number of attempts. If readiness cannot be proved, the run remains invalid.
Startup-to-first-result includes this readiness cost; it is not pure Pyright
initialize time. This is not a performance optimization or proof of sandboxing.
The historical P3.5 Linux JSON predates this correction and is retained
unchanged as non-authoritative smoke evidence.
