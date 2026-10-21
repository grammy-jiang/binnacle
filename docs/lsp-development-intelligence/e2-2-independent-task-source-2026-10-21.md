# E2.2 — Independent original-task source reconnaissance (2026-10-21)

**Decision: technical source-lead discovery GO on MacBook Pro; independent original human task-goal recovery remains OPEN/NO-GO for retrospective task certification.** E2.1's already frozen 49 anonymous request groups are unchanged. No recorded historical command, captured code, task instruction or agent session was replayed.

## Scope and method

- Use the existing owner-only E2.1 HMAC metadata checkpoint to confirm that current local JSONL evidence still produces the **same** recorded MCP request/result/error observations; the E2.2 normal path compares the saved bytes **without writing anything**. No missing checkpoint is silently recreated.
- Inspect the originating host's captured tool-call arguments **in place** for an *explicit* `workdir`/`path` under `~/Projects` with one coherent nearest `.git` repository root. Paths in arbitrary command text are not treated as project authority. An individual call with competing workdir/path roots disqualifies unique attribution.
- Within that repository, search only bounded text documents in a **7-day filesystem mtime window preceding the observed tool call** (maximum 350 files, 512 KiB per file) and compute exact, case-sensitive whole-token task-ID overlaps. The current mtime is **not** independent proof that document content existed unchanged at that historic time.
- Check native local Codex, Claude and Pi Agent sessions for an *identically named, same-host MCP tool* with matching canonical JSON arguments and start times within a strict tolerance. The presence of a prior user-role message is only a potential source lead: without a separate same-session/invocation identity, it **does not** establish the original ChatGPT user's goal. Incomplete session coverage invalidates candidate uniqueness; source timestamp/file mtime limitations are reported, never silently ignored.
- Tool arguments, source, document text, task IDs, local project names, agent prompts, session IDs and HMAC references stay on their originating host. Reports expose only fixed categories and aggregate counts; optional owner-only case evidence records use the `-e22-v2-goal-sources.json` suffix and **do not** promote `R0_unverified` cases.
- Existing ChatGPT conversation history independently preserves at least one explicit LSP/logging task instruction from this cohort, but no audited, exact Conversation → MCP request-group join was available; it was **not assigned to any case**, not counted as an accepted R1 task and not copied into the host-local manifests.

## Frozen cohort source-lead results

The original cutoff remains **2026-10-21T01:00:00Z** (12:00 AEDT, exclusive). This is a per-host source-availability assessment, **not task labels**.

| Measure | MacBook Pro (full E2.2) | Raspberry Pi (native narrow precheck) | Sextant (native narrow precheck) | Total/proven limit |
| --- | ---: | ---: | ---: | ---: |
| Selected E2.1 request groups | 14 | 20 | 15 | **49** |
| Groups with a single explicit local project repo | 5 | 0 | 0 | **5** |
| Groups with competing explicit repo anchors | 1 | 0 | 0 | **1** |
| Groups with bounded mtime-window text-document leads | 5 | 0 | 0 | **5** |
| Groups with matching literal task ID in such a document | 2 | 0 | 0 | **2 leads** |
| Verified original human task goal | 0 | 0 | 0 | **0** |
| Verified historic source snapshot/independent Gold Answer | 0 | 0 | 0 | **0** |
| Accepted historic R2/R3 replay-ready cases | 0 | 0 | 0 | **0** |

The Pi/Sextant counts use a separately executed host-local, **read-only narrow source precheck** aligned to the E2.2 explicit-repository/task-ID/mtime rules, not the full MacBook E2.2 package. They must **not** be reported as a three-host native E2.2 integration test. Both hosts successfully rejoined their 20/15 frozen E2 samples locally before checking source leads. Missing anchors do **not** prove no historic tasks were performed; command arguments may omit the workspace even when the agent was developing code.

MacBook's full E2.2 source scanner reported **441 older local agent session JSONL files excluded by a filesystem-mtime optimisation** and marked their exclusion as incomplete coverage. Thus **zero certified compatible external session links is not evidence that all historical agent sessions are absent**. Any candidate unique link would be suppressed while the scan is incomplete. Linux hosts' local agent-session archives have also been inventoried by source/type, but not fully covered by the Mac E2.2 implementation.

The Mac E2.2 report additionally found two bounded document-access errors; these are counted, not transformed into successful task labels. The two literal task-ID intersections need independent task-text verification, source-state dating and a link to the exact original human request. Until then, both remain **R0**, not R1/R2.

## Implementation and quality

- `scripts/lsp_e22_sources.py`: strict same-call explicit repository anchors, case-sensitive non-substring task IDs, bounded mtime-window project document source leads.
- `scripts/lsp_e22_sessions.py`: conservative same-host matching of candidate tool inputs, error-aware recursive traversal, symlink/invalid-timestamp/old-file/partial-JSON downgrades, no false unique correlation.
- `scripts/lsp_e22_goals.py`: frozen-cohort selection, prior E2.1 HMAC checkpoint byte comparison in default **read-only mode**, aggregate-only reporting and optional versioned private metadata packet.
- Supporting E2.1 parser correction in `scripts/lsp_e21_evidence.py` rejects malformed unrelated correlation IDs before dictionary use. `scripts/lsp_e21_recovery.py` adds a read-only existing checkpoint verification mode; no ambient `fsync` or packet publication occurs by default in E2.2.

MacBook synthetic E2.2 tests: **36/36 passed on CPython 3.10 and 3.14**. In the final combined run, E0/E1/E2/E2.1/E2.2 tests passed **149/149** and LSP P1 remained **373/373**; existing MCP surface contract tests remained **42 passed, 13 skipped, 2 xfailed**. The source and test modules are below 500 physical lines and conform to Ruff, formatting and architecture/import contracts. No production `src/binnacle` implementation, public tool, service runtime or feature toggle was changed.

Independent read-only reviewer initially returned REWORK for cross-server false matches, silent incomplete scans, repo mixing, partial task IDs, and symlink provenance, then additional negative tests found silent unreadable directory, old-mtime and missing-event timestamp gaps. After fail-closed fixes, the final review returned **limited technical GO**, explicitly distinct from proving a real task or complete agent-session census. The later read-only checkpoint fix received another limited GO from a separate static reviewer. All reviewers were prohibited from reading private user data/logs/session files or modifying the worktree.

## Next validation gate

**E2.2 manual task certification remains open:** use an independently accessible, contemporary original human request and an unambiguous **task-to-request-group correlation identifier**, not timing, a repository name or a matching ID alone. Reverify negative controls, provenance and exclusion counts; do not equate agent user-role messages with the original ChatGPT instruction.

**E2.3 remains open:** recover a clean dated source revision and complete relevant dirty/uncommitted working-tree state, then independently establish Gold Answers. If this frozen historical cohort cannot support that evidence, record it as non-replayable and use separately labelled prospective/synthetic frozen development tasks for E3–E5. Do not fabricate historic R2/R3 cases or tool-efficiency gains.

The optional Development Intelligence sub-server remains a **future default-off, explicitly enabled per-host capability**, not a running P2 implementation. [Architecture decision](adr-0001-focused-subserver.md).
