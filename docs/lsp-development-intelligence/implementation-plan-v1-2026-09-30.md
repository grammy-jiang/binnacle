# Development Intelligence / LSP — implementation roadmap

| | |
| --- | --- |
| **Status** | Session-sized roadmap split 2026-09-30 |
| **Current baseline** | `master` `f1493ee` |
| **Public MCP state** | No Development Intelligence tool approved |
| **Execution rule** | One work item = one focused ChatGPT session = one commit or explicit no-code decision |
| **Project index** | `docs/lsp-development-intelligence/README.md` |

## 1. How to use this plan

Do **not** ask one ChatGPT session to "implement Phase 1" or "add Pyright support".

Start one work item by ID. Read only the documents listed for that item, inspect the current
code again, complete the scope, run the stated validation, and stop.

A work item may be split further if new evidence shows it touches more than one subsystem.
Do not silently expand its scope.

### Session-size constraints

A normal work item should satisfy all of these:

- one primary behavior or one evidence question;
- normally no more than 1–3 new/changed production modules;
- one main test level;
- no provider-matrix run combined with benchmark-harness implementation;
- no public MCP surface change combined with product evaluation;
- no multiple provider implementations in one item;
- no deployment step combined with feature coding;
- one clear rollback point.

A session is complete when:

1. the scoped tests pass;
2. `git diff --check` passes;
3. applicable pre-commit hooks pass;
4. the work item has one commit, or a short decision record explains why no code was kept;
5. the worktree is clean.

### Revalidation rule

Before the first item of a new phase, or whenever master moved materially:

1. compare the design branch with master;
2. rebase;
3. check the relevant design assumptions;
4. update only the affected design file before coding.

Do not carry stale design assumptions into implementation.

---

## 2. Dependency map

~~~text
P0 test/benchmark foundations
  |
  +--> P1 protocol + lifecycle
  |      |
  |      +--> P2 provider profiles
  |              |
  |              +--> P3 private inspect_symbol experiment
  |                       |
  |                       +--> [GO?] P4 public inspect_symbol experiment
  |
  +--> P5 diagnostics experiment (after safe analyzer foundations)

P6 production provider expansion depends on measured demand + safety
P7 future retrieval/MCP evolution depends on earlier product evidence
~~~

Public-tool phases are conditional. A failed gate ends that product path; it does not block
the private protocol/provider work already proven useful.

---

## 3. Phase file map

| Phase | File | Purpose |
| --- | --- | --- |
| P0/P1 | `implementation-foundations.md` | test harness, benchmark foundation, protocol/lifecycle |
| P2 | `implementation-providers.md` | provider profiles and characterization |
| P3/P4/P5 | `implementation-product.md` | private/public product experiments |
| P6/P7 | `implementation-expansion.md` | later provider enablement and future design work |

Do not read later-phase files when executing an earlier work item.

## 4. Phase gates

- P0 gate: deterministic harness is trustworthy.
- P1 gate: private manager works and existing six-tool contracts are unchanged.
- P2 gate: provider compatibility/safety evidence exists.
- P3 gate: private semantic navigation either proves workflow value or stops.
- P4 gate: public `inspect_symbol` is optional and requires an explicit SHIP decision.
- P5 gate: public `check_code` is a separate optional decision.
- P6 provider enablement is per provider and demand-driven.
- P7 work requires a new design/benchmark first.

---

## 11. Recommended execution sequence now

The immediate sequence is:

1. P0.1 fake LSP server skeleton
2. P0.2 fake semantic responses
3. P0.3 fake notifications/server requests
4. P0.4 fake framing/data faults
5. P0.5 fake lifecycle/process faults
6. P0.6 fake analyzer
7. P0.7 standalone benchmark core
8. P0.8 resource sampling
9. P0.9 artifact identity
10. P0.10 matrix discovery
11. P0.11 harness review

Stop after each item. Do not start the next item in the same ChatGPT session merely because
the previous one completed quickly; first inspect the result and dependency assumptions.

---

## 12. Session handoff template

At the end of every work item, record:

~~~text
Work item:
Commit:
Files changed:
Focused tests:
Hooks:
Key finding:
Design assumption changed? yes/no
Next eligible work item(s):
Worktree clean? yes/no
~~~

This is the minimum context the next ChatGPT session should need in addition to the indexed
documents.
