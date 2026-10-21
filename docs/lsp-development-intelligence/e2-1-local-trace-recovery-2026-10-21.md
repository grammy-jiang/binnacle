# E2.1 — Opaque case linkage and historic MCP call-sequence recovery (2026-10-21)

**Verdict: Technical GO for bounded, host-local linkage and call-sequence metadata.**
**E2.2 task-goal recovery and E2.3 historical source/independent gold validation remain OPEN.**
No historical command was executed or replayed; no LSP runtime, provider, MCP public tool or running service was started/modified.

## 1. Cohort, method and privacy

Reuse the fixed E0/E1/E2 cohort ending **2026-10-21T01:00:00Z** (Sydney 12:00 AEDT, exclusive), seed `20261021`, and the 49 opaque case references previously stored in each host's owner-private `~/.local/state/binnacle/dev-intelligence-e2/pilot-20261021-noon.json`.

The stand-alone, read-only `scripts/lsp_e21_recovery.py` uses the existing E01/E02 parsers to reconstruct selected groups **in place** from private full-capture JSONL and readonly Session Observability SQLite. It recomputes the selected group's HMAC using the local private key, validates its frozen stratum, original sample quality and case cardinality, then reconstructs the tool labels, relative ordering, result/error state, truncated flags, nonzero exits and timing. Typed request IDs, impossible chronology, duplicate request consumers, missing timestamps and evidence changes fail closed or yield explicitly uncertain sequence evidence. Requests are filtered by the original UTC cutoff; original user instructions, raw command bodies, file paths and results never enter console/report output.

A separate evidence helper, `scripts/lsp_e21_evidence.py`, classifies **presence only** of optional MCP task metadata and exact *standalone* Git revision/porcelain requests when an explicit, trustworthy returned result exists. A 40-character Git SHA or a clean `git status` result is **not** by itself proof of a clean historical working-tree snapshot. A Boolean exit code or multiline Shell construction cannot certify a Git result.

When explicitly invoked with `--write-local-review`, E2.1 atomically stores only per-case status/timing categories, opaque case references and a private HMAC checkpoint of the complete captured MCP request/result/error evidence. The owner-only packet is `pilot-20261021-noon-e21-v2-review.json` in the same host-local state directory, mode `0600`. The earlier Mac proof-of-concept `-e21-review.json` is superseded and must not be treated as the final checkpoint. **Original E02 capture bytes were not independently committed when E2 sampled**, so E2.1 can bind present evidence for *subsequent* checks but cannot retrospectively prove no capture content changed between E2 and E2.1.

## 2. Three-host frozen recovery

| Measure | MacBook Pro | Raspberry Pi | Sextant | Combined |
| --- | ---: | ---: | ---: | ---: |
| Previously selected opaque case refs | 14 | 20 | 15 | **49** |
| Exact local case identities relinked | 14 | 20 | 15 | **49** |
| Observed tool-call sequence entries in selected groups | 280 | 290 | 127 | **697** |
| Groups with unpaired calls | 0 | 0 | 0 | **0** |
| Groups with uncertain temporal order | 0 | 0 | 0 | **0** |
| Request-before-tool timestamp anomalies | 0 | 0 | 0 | **0** |
| Error or nonzero-exit tool calls (not unique task failures) | 15 | 10 | 7 | **32** |
| Truncated tool-result records (not distinct tasks) | 20 | 2 | 0 | **22** |
| Strict standalone Git HEAD result evidence | 0 | 0 | 0 | **0** |
| Strict standalone clean Git porcelain evidence | 0 | 0 | 0 | **0** |
| Selected request payloads with populated `task` field | 0 | 0 | 0 | **0** |
| Independently verified user task goals | 0 | 0 | 0 | **0** |
| Independently verified code snapshots / gold | 0 | 0 | 0 | **0** |
| R2/R3 replay-ready historic cases | 0 | 0 | 0 | **0** |

The 697 entries are observed tool calls within **49 selected request groups**, not distinct development tasks, executed Shell commands, model steps or saved tokens. Successful local relinking proves presence and identity consistency in the available capture, not completeness of the original human instructions or correctness of agent work.

The 49 groups include the **11 E2 negative-control groups**, whose polling/noncandidate actions cannot be attributed to an LSP feature gain. The E2.1 tool neither renames them as development tasks nor promotes any case beyond `R0_unverified`.

## 3. Implementation and independent verification

- Two test-only E2.1 modules: `scripts/lsp_e21_recovery.py`, `scripts/lsp_e21_evidence.py` (both under 500 physical lines).
- Synthetic tests: `tests/scripts/test_lsp_e21_recovery.py` and `test_lsp_e21_adversarial.py`, **29/29 passed natively on MacBook, Raspberry Pi and Sextant**. MacBook CPython 3.10 and 3.14 both passed the full E2.1 suite.
- Linux test+program source matched the MacBook SHA-256 verified bundle `ec311db68b4c9c6e09bd3a576899f498292a2d0a94d612691121bf686975384b`; unpacked/executed in an existing **/tmp synthetic fixture directory only**, not production.
- Private packets were created by the E2.1 CLI on each host, verified locally as owner-only and R0, with correct ordered tool-entry counts. No private payload or case lookup HMAC was copied into Git or transferred among hosts.
- An independent read-only source review first returned **REWORK** for reused request identities, ignored missing-time evidence, multiline Git recognition, incomplete checkpoints, manifest type confusion and request chronology. A second review found missing frozen hint comparison and loose Python Boolean result type checks. All actionable findings were fixed and covered by synthetic tests. The final independent read-only review returned **limited GO** for E2.1 evidence relinking only. Reviewers were explicitly barred from opening actual private logs, manifests, Session Observer DBs or connected/network resources.
- Full repository CI, coverage-policy and real provider A/B remain separate future release gates. No existing production `src/binnacle` source is changed.

## 4. Reproduction on a host, after authorization

Without persisting a new packet (read-only):

```bash
python3 scripts/lsp_e21_recovery.py \
  --capture-dir "$HOME/.local/state/binnacle/full-capture" \
  --observer-db "$HOME/.local/state/binnacle-session-observability/sessions.sqlite3" \
  --private-dir "$HOME/.local/state/binnacle/dev-intelligence-e2" \
  --batch pilot-20261021-noon
```

To freeze a *local metadata-only* follow-up packet, also pass `--write-local-review`. The final packet name is versioned; conflicting bytes do not overwrite an earlier checkpoint. Never commit local `~/.local/state/binnacle/dev-intelligence-e2` contents.

## 5. Next independent evidence gates

**E2.2:** use separately authorized contemporary project tasks/issue/Chat Mode context to identify original user goals without conflating a request group with a whole task. Task text is absent from the frozen MCP request `task` field across this cohort. The private packet's provisional subgoal labels are not verified R1 user-goal annotations.

**E2.3:** independently establish a clean *historical* source revision, complete relevant uncommitted state where possible, and an independently checked answer. Preserve R0/R1 exclusion counts and negative controls. Without this proof, no E3 retrospective R2/R3 replay and no performance claims. A synthetic/prospective frozen task set must be labeled as such, not silently presented as recovered history.

The separate optional-subserver feature decision is recorded in [ADR-0001](adr-0001-focused-subserver.md): Development Intelligence is **off and unmounted by default** to avoid adding unnecessary tool-schema tokens for non-developers, and is explicitly enabled per host only after product/runtime approval. This documentation is **not** an implemented P2 configuration toggle.
