# P3.6 offline raw-evidence consistency preflight (POC)

**Scope:** explicit operator-selected local JSON artifacts, **no provider launch,
network operation, repository edits, public MCP registration, release or READ
admission**. This is not the authenticated P3.6 evidence importer required for
P4/production.

## Implemented checks

The private CLI `python -m scripts.lsp_p36_import` requires two explicit,
absolute JSON artifact paths (P3.4 native breadth and P3.5 benchmark) and a
SHA-256 pin for each. Input files must be bounded regular files opened with
`O_NOFOLLOW`; JSON duplicate keys, NaN, malformed records and size violations
are rejected without printing source content or filenames. Digests supplied by
an operator prevent accidental mismatch **but do not authenticate the operator
or the producer**.

The verifier cross-checks P3.4's four script digests against the currently
checked-out first-party files and rejects purported successful providers when
their synthetic fixture files, cleanup, protocol completion or semantic gold
are inconsistent. It verifies P3.5's harness digest, uv.lock digest, exact
optional `multilspy` commit, self-reported valid/cleanup evidence, complete
per-operation gold counts, and positive observed RSS with no sampling errors.

It does **not** independently witness the raw LSP messages or OS side effects;
it does not validate real-repository revision identity or reconstruct individual
response gold positions. There is no verified P3.3 safety attestation, matching
Pyright P3.4 method evidence, or authenticated independent reviewer identity.
**Do not treat report `valid=true` or the local recomputed SHA as
external proof.**

## Explicit result and usage

```bash
python -m scripts.lsp_p36_import \
  --p34 /absolute/path/to/breadth-report.json \
  --p34-sha256 <64-hex-digest> \
  --p35 /absolute/path/to/benchmark-report.json \
  --p35-sha256 <64-hex-digest>
```

For well-formed source-consistent inputs, the report is
`selection=REWORK`, `resource=REWORK`, `read=NO-GO`,
`public_release=NO-GO`, `attestations_verified=false`. The embedded
P3.6 `EvidenceBundle` has **all three stages null**. Exit code is **1**,
never an authorizing success. Missing/corrupt/tampered evidence emits a
sanitized **NO-GO** report and exits **2**.

On Sextant (2026-10-23), the first local prototype was exercised on the
actual P3.4 postreview report (9 provider fixtures pass, 1 unavailable)
and the reviewed 18-source Binnacle P3.5 single-resident report (150 claimed
correct benchmark requests). Script and harness fingerprints matched the
checked-out `1325e30` candidate; the observed report remained **REWORK /
READ NO-GO**. Raw producer JSON was only read, never edited.

## Why this is not acceptance evidence

1. Source checks compare bytes to a *local working tree*. A separately
   authenticated Git commit and independent witness chain are still missing.
2. P3.4 covers TypeScript, JS, C/C++, Rust, Markdown, Bash, YAML/JSON; it
   does not contain matching Pyright method capability evidence for P3.5.
3. P3.5's real workload is a reviewed **subset** of 18 files copied to a
   disposable directory, not whole-repository indexing or a production agent
   workload. The original benchmark is self-reported.
4. P3.3's Node launch provenance is improved but the child is not yet
   confined by an enforced Linux/macOS filesystem + network + process sandbox.
5. Trusted reviewer authorization, robust source-specific importers, CPU idle
   time series, soak and eviction witnesses, and hard enforced resource limits
   are missing.

**Next gate:** an authenticated, signed/digest-bound evidence pipeline with
separate independent review and real OS isolation proofs. No policy or
runtime changes should authorize READ from this tool's output.
