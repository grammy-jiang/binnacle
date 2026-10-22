# P3.6 — Offline provider selection and resource policy

**Stage decision: REWORK. READ and P4/P5 public release: NO-GO.**
This change supplies an optional offline evaluator and an evidence import contract.
It does not complete the provider/resource acceptance gate. Final P3.3–P3.5
evidence and independent source-bound P3.6 review are still required.

Baseline: `66697d280cc29991c4500e46eb2641ef91f84541`.
Development target: Sextant, Linux ARM64, 2026-10-22.
The checkout is `binnacle-lsp-p36-policy-20261022` on its isolated feature branch.
No provider, project workload, service, or network probe was run for P3.6.
No commit, push, rebase, deployment, public tool, or production default change
is part of this work.

## Evidence ledger and unsupported data

| Input | What was checked | Admitted to the decision dataset | Outstanding dependency |
| --- | --- | --- | --- |
| P3.1 at the baseline | `config_development_intelligence.py` and `lsp_profile_assessment.py` | Existing admission rules only | Exact operator profile and executable still need owner checks at launch |
| P2.6 resident manager | Committed resident-manager report | Configured count 1–8; lifecycle behavior, not a resource measurement | Capacity/RSS/CPU/TTL/deadline measurements |
| P3.3 team status | User handoff: READ NO-GO, explicit-trust-only, no complete OS sandbox | Restrictive planning constraint only; no final payload or review imported | Immutable final audit, exact scope and independent review |
| P3.4 sibling worktree | Read-only Git inventory at baseline `66697d2`; four untracked breadth probe scripts | Nothing; live untracked work is not final evidence | Final adapter/discovery/initialize records; not security certification |
| P3.5 team status | User handoff: code and timing evidence pending | Nothing | Correctness-first measurements and independent review |
| September tiny probes | Historical tables in the mapbook and performance design | Nothing | Small samples, different scope/identity, missing review; cannot rank providers |
| P3.6 unit fixtures | Invented numbers and invented reviewers, explicitly labeled in tests | Test controls only | Never copy these into a measurement report |

The sibling `~/Projects/binnacle-lsp-p34-breadth-20261022` was not modified.
Its transient scripts were not executed or copied. Historical installation
claims also differ: make-ls was absent in September but found by a later shell
inventory. Neither establishes current service availability or exact identity.

The checked-in [pending bundle](p3-6-pending-evidence.json) records all three
stages as `null`. It intentionally contains no executable identity, review,
latency, throughput, CPU, RSS, measured TTL, or measured deadline claims.

## Capability and selection matrix

These are candidacy decisions for an explicitly opted-in private profile.
The actual default-off configuration remains NO-GO for every provider.
All rows have **READ NO-GO** and **public-release NO-GO**.

| Provider / language | Capability evidence usable now | Private selection | Resource decision | Reason / next dependency |
| --- | --- | --- | --- | --- |
| Pyright / Python | Prior functional evidence; no complete matching P3.3–P3.5 dataset | REWORK | REWORK | Only P3.1 private adapter allowlist member; exact final audit, correctness, resources and review missing |
| TypeScript LS / TypeScript | Historical tiny fixture; P3.4 pending | NO-GO | NO-GO | No P3.1 runtime admission; separate TS corpus and complete tsserver child accounting required |
| TypeScript LS / JavaScript | Historical tiny fixture; P3.4 pending | NO-GO | NO-GO | JS evidence cannot be inferred from TS; same admission gap |
| clangd / C | Historical tiny fixture; P3.4 pending | NO-GO | NO-GO | No P3.1 admission; compile database and cache effects unresolved |
| clangd / C++ | Historical tiny fixture; P3.4 pending | NO-GO | NO-GO | Separate C++ corpus; C results do not transfer |
| rust-analyzer / Rust | Historical settled fixture; P3.4 pending | NO-GO | NO-GO | No P3.1 admission; Cargo/build/proc-macro execution trust unresolved |
| Marksman / Markdown | Historical link/heading fixture; P3.4 pending | NO-GO | NO-GO | No P3.1 admission; root/marker and cross-root behavior need evidence |
| Bash language server / Shell | Historical sourced-function fixture; P3.4 pending | NO-GO | NO-GO | No P3.1 admission; helper subprocess trust and method scope unresolved |
| make-ls / Makefile | Conflicting historical availability; exact product unresolved | NO-GO | NO-GO | No P3.1 admission; identity, recipes/includes and correctness unresolved |
| YAML language server / YAML | Catalog claims; no admitted final probes | NO-GO | NO-GO | No P3.1 admission; schema/network behavior unresolved |
| JSON language server / JSON | Catalog claims; no admitted final probes | NO-GO | NO-GO | No P3.1 admission; exact server, schema/network behavior unresolved |
| gopls / Go | Future candidate only | NO-GO | NO-GO | Outside current configuration/provider scope |
| Ruff LSP/CLI; Pyright CLI | Separate diagnostics candidates | NO-GO | NO-GO | Outside this navigation policy; completion and side effects require separate evidence |

No provider earns an evidence-backed GO in this synthesis. Discovery,
advertisement, correctness and security remain separate axes. The evaluator
handles definition, references, hover, document symbols and workspace symbols
individually. It excludes diagnostics, editing and command methods. Supporting
a schema method does not add that method to a runtime adapter.

## Resource decision matrix

| Item | Existing contract | P3.6 measured value | P3.6 decision |
| --- | --- | --- | --- |
| Resident instances | Configurable integer 1–8; default 2 | Not available | Preserve config; refuse a proposed count above its cap |
| Idle TTL | Config default 120 seconds | Not available | No tuning; exact tested envelope and idle-eviction evidence required |
| Request deadline | Config default 30 seconds | Not available | No tuning; exact tested envelope and deadline evidence required |
| Warm latency | At least 30 exploratory samples; 100 preferred for stability | Not available | No ranking; require all gold checks to pass |
| Process-tree RSS | P2.6 is not an RSS quota | Not available | Require complete-tree samples; maxima remain observations |
| Idle CPU | No measured ceiling | Not available | Require idle tree samples; never infer throughput |
| Cold / settling / soak | Must be recorded separately | Not available | No synthetic substitute for real observations |
| Capacity and cleanup | P2.6 lifecycle evidence | No P3.5 resource result | Require explicit tested capacity, idle/LRU, deadline and cleanup assertions |

A single resident provider may be proposed for a disposable private experiment
as **PROVISIONAL**. That is a conservative experiment choice, not a measured
memory limit. This evaluator changes no configuration and suggests no numeric
CPU/RSS quota. It never divides host RAM by a historical RSS value to infer
capacity. A raw-LSP result cannot establish Binnacle overhead or integrated
deadlines. `measurement_path` must match exactly.

## Offline contract and decision semantics

`scripts/lsp_p36_evidence.py` defines strict, version-1 typed inputs.
`scripts/lsp_p36_policy.py` provides the pure `evaluate(request, bundle)` function.
`scripts/lsp_p36_evaluate.py` reads two operator-selected JSON files and prints
a JSON report. Nothing imports these modules into runtime composition.
No executable, URL, artifact reference or workspace in a record is followed.

The operator-owned request is separate from the imported evidence. It carries
the expected identity, current configuration, proposed experiment settings,
and independently verified reviewer identities. Matching includes provider
version, executable/profile/adapter digests, Binnacle commit, host, OS, arch,
runtime/environment, corpus/gold digests, language, method, workload and
measurement path. Any difference blocks GO. Reusing an audit for another
scope requires a separately reviewed scoped record; an importer must not
silently replace its identity.

The retained environment manifest must cover provider package contents, helper
binary identities, initialization options, client capabilities and dependency
versions. `environment_sha256` binds that manifest. Hashing only a launcher
script or copying a version string does not establish that environment.

Each stage must be final and have an independent GO review bound to its entire
canonical payload digest. The producer cannot review its own payload. Unknown
reviewers, absent reviews and changed payloads block GO. Artifact references
and SHA-256 digests remain in the inputs; the output records request/bundle
digests and every stage payload digest, including refused stages. Keep the
inputs with the output to preserve the full provenance chain.

**This is an attestation checker, not a signature or raw-artifact verifier.**
Reviewer names and digest strings alone cannot authenticate a review or prove
a measurement. The trusted importer must verify retained artifact bytes,
review provenance and exact source before adding a reviewer to the request.
Do not accept a provider-supplied request or reviewer allowlist. A malicious
operator input can lie; this offline result is never launch authority.

- **NO-GO:** present evidence violates admission, trust, availability,
  advertised-method or correctness requirements, exceeds the configured cap,
  or carries an independent NO-GO review.
- **REWORK:** required evidence is absent, mismatched, draft, unreviewed, too
  small, incomplete, or lacks the exact tested resource envelope.
- **GO:** all checks pass for a private experiment at this exact scope only.
  It is not overall P3 acceptance, P4 authorization, READ or release approval.

Selection and resources are deliberately coupled: incomplete resource evidence
also prevents selection. Rejected inputs produce no accepted measurement fields.
Valid observations use nearest-rank p50/p95/p99 and maximum observed tree RSS
and idle CPU. At least 30 samples are required for each stream. These are an
exploratory floor, not a statistical confidence guarantee. A reviewed soak and
complete-tree/capacity/idle/deadline/cleanup assertions are also required.
No TTL or deadline is calculated from latency percentiles.

Schema errors return exit 2 and a sanitized NO-GO report. A valid refusal
returns exit 1. Scoped GO returns exit 0. Tests of GO use invented data only.
Both `read` and `public_release` remain NO-GO even for the positive control.

## Re-evaluation after P3.3–P3.5 finish

1. Obtain final immutable source commits, artifact bytes and independent review
   records. Do not import sibling working files as final evidence. Verify
   artifact SHA-256 values and reviewer identity outside the evaluator.
2. Export the JSON schemas from `PolicyRequest.model_json_schema()` and
   `EvidenceBundle.model_json_schema()`. Map final evidence into these contracts
   explicitly. Do not infer missing fields. Retain original raw artifacts and
   a mapping log with every rejected or unsupported field and its reason.
3. Create one request per exact provider/language/method/workload/path identity.
   Use `fingerprint(profile)` for `profile_sha256`. Preserve all other exact
   source identities. Set `trusted_reviewers` from verified independent records,
   never from the incoming evidence's own requested allowlist.
4. Populate each stage with `review=null`. Give the independent reviewer the
   normalized record and retained source artifacts. Bind the review to
   `record.payload_digest()` and retain its own artifact reference/digest.
   A digest computation by the author is not independent approval.
5. Leave unavailable stages null. Run the offline command below. Save its
   output alongside both input files and the import mapping log. Compare
   reason codes and digests against the previous result. Re-run after any
   identity, sample, configuration or source change.
6. Update this matrix only for the exact accepted scope. Obtain separate
   source-bound review of P3.6 before closing its gate. Broader provider
   admission, integrated overhead, real-workload acceptance and P4/P5 decisions
   remain separate work; this command cannot grant them.

```bash
uv run python -m scripts.lsp_p36_evaluate \
  /tmp/p36/operator-request.json /tmp/p36/final-evidence.json \
  > /tmp/p36/decision.json
```

Use [the pending bundle](p3-6-pending-evidence.json) until final evidence exists.
The request still needs actual operator-owned identity/configuration; do not
invent digests to turn an incomplete request into a GO.

## Validation and remaining gates

Final evaluator location is `scripts/`; no production Python file is changed.
This avoids adding an offline analysis module to the server's eager startup
import set. Tests are therefore in `tests/scripts/`, with synthetic data in
`tests/fixtures/lsp/decision_evidence.py`.

| Check | Result on Sextant, CPython 3.13.16 |
| --- | --- |
| P3.6 focused suite, fixed seed 12345 | **165 passed**; all three evaluator modules have **100% statement and branch coverage** (222 statements, 46 branches) |
| P3.1/configuration/P2.6 regression plus startup-set tests | **112 passed, 1 environment error**: a startup test writes beneath the read-only home directory |
| Focused Ruff lint/format, mypy, Bandit | Passed |
| Focused Markdown lint | All three changed Markdown documents passed pinned markdownlint-cli2 0.23.3 |
| Architecture and import boundaries | 281 runtime modules; zero forbidden dependencies; all 25 import contracts kept |
| Startup module manifest and source ownership | Startup manifest unchanged and current; `manifest_coverage()` returned `([], {})` |
| Strict module-size gate | Passed; no new file exceeds 500 lines |
| OS6 inventory | Regenerated and checked; complete inventory retained at `/tmp/binnacle-p36-os6-source-reconciliation.json` |
| Pre-commit all-files gate | **Incomplete**: initial hook setup hit read-only npm cache; retry with writable caches reached the 300-second bound while installing hook environments (exit 124) |
| Pre-push managed two-lane suite, seed 12345 | **Failed**: parallel lane 101 failed, 3702 passed, 9 skipped, 110 errors; ordinary-process lane 1 passed |
| Coverage-policy tox gate, seed 12345 | **Failed** in unit lane: 11 failed, 3259 passed, 4 skipped, 110 errors; full coverage gate did not run |

The broad failures include home-directory writes blocked by this workspace's
filesystem policy and MCP initialization/full-capture failures. A clean archive
of baseline `66697d2` reproduced one MCP handshake failure and one home-write
error. This confirms those two representative failures predate P3.6; it is not
a claim that every broad failure was independently diagnosed. No baseline
tests or environment policy were weakened to force a pass.

The generated OS6 inventory includes extensive older source drift unrelated to
P3.6. Its full recapture was checked and retained under `/tmp`; the existing
repository-wide artifact was left unchanged to keep this handoff scoped.
Integration must recapture the inventory again after the concurrent teams merge.

The development doctor initially found no `.venv` or installed Git hooks.
`uv sync --locked --group dev` created this checkout's environment with a
writable `/tmp` uv cache. Shared Git hooks were left unchanged. The usage guard
command is unavailable on PATH. No unattended manager was started.

Reproduce the focused check:

```bash
uv run pytest -q tests/scripts/test_lsp_p36_policy.py \
  tests/scripts/test_lsp_p36_evaluate.py --randomly-seed=12345 \
  --cov=scripts.lsp_p36_evidence --cov=scripts.lsp_p36_policy \
  --cov=scripts.lsp_p36_evaluate --cov-branch --cov-report=term-missing \
  --cov-fail-under=0
```

The zero aggregate floor in this focused command isolates measurement from the
repository-wide coverage gate; the observed coverage is 100%. It does not
change repository coverage policy. These tests do not substitute for independent
review.

Local logs: `/tmp/binnacle-p36-final-focused.log`,
`/tmp/binnacle-p36-final-precommit.log`, `/tmp/binnacle-p36-final-prepush.log`,
`/tmp/binnacle-p36-final-coverage.log`,
`/tmp/binnacle-p36-baseline-control.log`, and `/tmp/binnacle-p36-regression.log`.

Generated schema exports are available at `/tmp/binnacle-p36-request-schema.json`
and `/tmp/binnacle-p36-evidence-schema.json`. The complete Python compatibility
matrix was not run for this offline script change. The broad gates remain
unresolved; this handoff does not claim repository-wide green CI.

Unresolved dependencies: final P3.3 safety evidence; final P3.4 capability
records; P3.5 correctness/resource and integrated-overhead evidence; real-scope
coverage; independent P3.6 source review. No OS-enforced sandbox certificate
exists in the admitted dataset. READ remains NO-GO.

## Subsequent controlled medium-fixture evidence (2026-10-23)

The later [P3.5 Sextant medium measurements](p3-5-controlled-medium-sextant-2026-10-23.md) supersede the earlier statement that no measurements at all exist, but **do not turn the P3.6 final bundle into GO evidence**. Three sanitized native records use Pyright 1.1.413 and multilspy `08ba0db`: two independent cold runs with two resident instances and one with a single resident, each with 100 repeats per operation per instance, exact synthetic gold and clean process shutdown.

- Two residents: Manager definition p95 150.0/156.8 ms; observed tree RSS 825.2/845.2 MiB. Both exceed the provisional 100 ms and 512 MiB targets.
- One resident: Manager definition p95 108.8 ms; observed tree RSS 427.9 MiB. It satisfies the provisional RSS budget in this one observation but still exceeds the 100 ms latency target.
- All six measured operations returned correct gold locations/contents with no errors or timeouts in all three runs. These are synthetic data, not representative real-workspace or agent-value results; p50/p95/p99 do not prove hard resource limits, idle CPU, long-soak, or authorization.

**Decision remains REWORK** for Pyright selection and resource policy. The P3.6 evidence bundle intentionally retains null review-qualified safety/capability/measurement inputs; only an independently verified final payload with exact identity and scope may populate those fields. A provisional one-resident private experiment can be proposed, but production defaults, READ annotation, resource quotas and public tools remain unchanged.
