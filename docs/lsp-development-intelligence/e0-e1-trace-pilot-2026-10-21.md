# E0/E1 retrospective MCP trace pilot — 2026-10-21

**Verdict:** GO for anonymous host-local opportunity mining; **NO-GO for claiming measured AI Agent savings or automatically choosing a public MCP tool**.

**Frozen cohort:** From each host's own full-capture activation until 2026-10-21 01:00:00 UTC, equivalent to 2026-10-21 12:00 AEDT (exclusive). Hosts activated at different times. Host call totals are not time-exposure-normalized rates.

**Source and privacy:** The opt-in local full-capture JSONL and read-only session-observability SQLite database. Original commands, source text, file paths, raw results, request hashes and other private identifiers were inspected only inside their originating machine. No raw records were exported to the model, copied into this repository or replayed as commands.

**Implementation:** scripts/lsp_e01_trace.py, scripts/lsp_e01_patterns.py and scripts/lsp_e01_observer.py; tests/scripts/test_lsp_e01_trace.py, test_lsp_e01_robustness.py and test_lsp_e01_window_bounds.py. Separate from the Binnacle production logger, tools and P2 runtime.

## 1. Frozen corpus and linkage quality

| Metric | MacBook Pro | Raspberry Pi | Sextant | Total |
| --- | ---: | ---: | ---: | ---: |
| MCP tool calls | 352 | 827 | 127 | **1,306** |
| Request arguments paired exactly | 352 | 827 | 127 | **1,306 / 1,306** |
| Calls with trustworthy request-group attribution | 280 | 417 | 127 | **824** |
| Distinct attributable request groups | 14 | 28 | 15 | **57** |
| Calls without trustworthy request grouping | 72 | 410 | 0 | **482** |
| run_command tool calls | 225 | 344 | 93 | **662** |
| read_file tool calls | 47 | 119 | 0 | **166** |
| search_text tool calls | 10 | 43 | 0 | **53** |
| job_status tool calls | 30 | 173 | 34 | **237** |

The 824 attributed calls are assigned by exact on-host generation/call to observer request hash to unambiguous tunnel base, or by an explicitly formatted forwarded turn ID. Missing/ambiguous joins cannot be inferred by timestamp. A **request group is not a development task or a model reasoning step**.

The frozen window contained no malformed JSONL rows, duplicate tool events, observer-key ambiguity, orphan terminal events or unpaired request/tool arguments. Every included tool call had a corresponding result/error event within the window. Only post-activation history can be evaluated with this content fidelity.

The local full-capture collector does not apply a string-length clip; however, upstream run_command tool output can be shortened before capture, spool files may later be pruned, and user prompts/model context/source working trees are not automatically reconstructable. The MacBook sample contains one command marked incomplete and the Pi sample includes five invalid command inputs and five missing search patterns. These are unknown/missing evidence, not zero demand.

## 2. Lexical candidate frequencies (nonexclusive; NOT verified intent)

| Locally classified command pattern | MacBook Pro | Raspberry Pi | Sextant | Total |
| --- | ---: | ---: | ---: | ---: |
| Git status/log/show/diff-like inspection | 43 | 86 | 14 | **143** |
| Git diff/show/blame-like change inspection | 25 | 43 | 0 | **68** |
| Shell text searches | 56 | 90 | 19 | **165** |
| Shell source reads (cat/sed etc.) | 119 | 70 | 20 | **209** |
| Test invocation candidates | 29 | 41 | 3 | **73** |
| Lint/type-check invocation candidates | 2 | 18 | 2 | **22** |
| Declaration-oriented / structural text searches | 3 | 3 | 0 | **6** |

These labels are lexical and overlapping. A long multi-command shell payload might match several categories even if an internal branch never executed. Incomplete or redacted strings are not classified as full original commands. The 237 job_status calls are a separate Commands/polling optimization issue and must not be credited as LSP savings.

## 3. Strict chronological request-group windows

The sequence detector requires a valid request/tool match, unambiguous group, distinct timestamps, a bounded lookahead of five calls/five minutes, or ten calls/fifteen minutes for change-to-test sequences. A failed test is usable only if its terminal result precedes later inspection.

| Candidate observed sequence | MacBook windows / groups | Raspberry Pi windows / groups | Sextant | Combined windows / groups |
| --- | --- | --- | --- | --- |
| Git change inspection then read_file/search_text | 7 / 1 | 3 / 1 | 0 | **10 / 2** |
| search_text then read_file | 2 / 2 | 1 / 1 | 0 | **3 / 3** |
| Structural search then read_file | 0 / 0 | 0 / 0 | 0 | **0 / 0** |
| Git change then source inspection then test | 0 / 0 | 0 / 0 | 0 | **0 / 0** |
| Lint/type-check then source inspection | 0 / 0 | 0 / 0 | 0 | **0 / 0** |
| Completed failed test then source inspection | 0 / 0 | 0 / 0 | 0 | **0 / 0** |

The 10 change/navigation windows come from **just two groups**, not ten independent tasks. The three search/read windows come from three groups. Zeros mean **not observed under stringent grouping**, not no actual need. Pi alone has 410 calls without confident cross-call grouping. Do not combine windows or divide by calls to invent a model-step savings percentage.

## 4. Conservative priority implications

1. **Highest E2 investigation priority: analyze_change and related-test impact.** Change-oriented shell traffic is frequent, with 10 strict Git-to-source windows, but independent sample diversity is poor. Inspect task goals and source-commit availability before treating any example as a verified change-impact question.
2. **First practical private semantic API candidate remains inspect_symbol.** Exact text search and file reading are common, and search/read windows appear in three groups. Only six declaration-oriented query labels were seen, however, with zero strict symbol-query/read windows. This does not yet prove symbol navigation is the bottleneck.
3. **Check_code needs independent comparison against existing shell-based diagnostics.** Twenty-two lint/type-check and 73 test labels are insufficient to claim a diagnostic-tool win, particularly with zero confidently linked post-failure inspection windows.
4. **Defer search_code_structure implementation selection.** The six broad structural-query matches have not been independently verified as actual AST-query demand.

**Do not change P2 architecture or publish a new MCP tool based on these rankings.** The next evidence task is E2: review a small, stratified set of independent local candidate and negative-control episodes (target around 40–60 where available), count irrecoverable original task goals and mutable source states, and build E3 gold tasks only from defensible R2/R3 grades. Several days of future observations may be required for independent samples. Actual benefit is a later prospective, correctness-first agent A/B measurement.

## 5. Reliability, safety and limits

- Raw files are streamed in place and output is aggregate-only. No arbitrary captured shell command is executed, and no source paths, command arguments, request IDs or per-value hashes are exported.
- The SQLite join uses read-only mode and query-only settings. Unresolved alternative hashes, duplicate or malformed events, mismatched typed request identifiers, incomplete timestamps and impossible outcome chronology are excluded from confident windows.
- Full input matching compares the original MCP tool name and exact canonical argument digest locally; sanitized name collisions cannot be treated as exact identity.
- Timestamp parsing handles explicit UTC and timezone offsets, with a fixed exclusive UTC cutoff to prevent E0/E1's own later activity inflating the pilot. Appended records after the cutoff affect only explicit excluded/scanned-row bookkeeping. The observer SQLite mapping is read at analysis time, not from an immutable noon snapshot; later ambiguous hash joins could change attributable group counts.
- Synthetic tests covered malformed JSON, redactions/truncation markers, fake identities, different event orders, negative chronology, time-window ties, lexical false positives, and no raw-data disclosure.
- Independently reviewed E0/E1 code: repeated REWORK findings were corrected and the final read-only reviewer returned GO for retrospective anonymous opportunity metadata only. The [independent review trail](e0-e1-independent-review-2026-10-21.md) records all closures.
- Final synthetic suite: 45/45 passed on each host; MacBook also passed Python 3.10 and 3.14. Pi final transfer bundle SHA-256: 139a843553e5eda4d3e586b0819b9ca9617cc5672a7193f6c5258d9d55d6bf35.
- This pilot does not include historical user prompts, total model tokens, full repository snapshots, causal counterfactuals, a completed real-provider audit, or an AI Agent success rate.

**Outcome:** Continue evidence validation under E2. Keep P2 implementation unstarted and the existing 6/8 MCP tool surfaces unchanged.
