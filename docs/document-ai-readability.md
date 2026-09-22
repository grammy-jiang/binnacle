# Document AI-readability policy

Status: design. Current enforcement target is warning-only.

## 1. Objective

The relevant property is not conventional prose style alone. Binnacle should help authors
keep Markdown efficiently retrievable through `search_text` + bounded `read_file` calls.

`read_file` currently returns at most 24,000 content characters in one call. Therefore a
large file can still be AI-friendly when headings create small, addressable semantic
chunks.

## 2. Current tool split

- `markdownlint-cli2`: Markdown syntax/structure correctness; existing blocking lint.
- future lightweight Binnacle checker: MCP/AI retrieval readability; warning-only.

Do not use whole-file line count as the primary metric.

## 3. Proposed signals

### File size

A file larger than the single-read budget is informational: it cannot be dumped whole in
one `read_file` call, but this is not by itself a defect.

### Heading-addressable chunk size

Parse Markdown structurally. For each heading, measure the source characters until the
next heading. A chunk that exceeds the single-read budget is a useful warning because the
agent cannot retrieve that smallest heading-addressable unit in one bounded read.

Initial policy should be warning-only, with the 24,000-character `read_file` budget as the
first meaningful boundary. Strong/severe levels can be introduced only after measurements
across real repositories; do not invent hard gates now.

### Large headingless documents

A large document with no headings is equivalent to one large addressable chunk and should
receive the same warning.

## 4. Why whole-file size is not enough

A measurement on Binnacle's current main documentation found large files whose heading
structure remains easy to retrieve. For example, `docs/agent-toolset-design.md` is about
50k source characters but its largest next-heading chunk is only about 6.5k. Splitting
such a document solely to satisfy a file-size lint would reduce coherence without improving
agent retrieval.

## 5. Implementation direction

Prefer a real Markdown parser, not regular expressions. The checker can reuse parser
semantics already present in the Markdown lint ecosystem and report path, heading, source
range, and source-character size. Keep policy values in `quality-policy.json` rather than
hard-coding deployment/project preferences into the checker.

## 6. Deferred option: Vale

Vale is intentionally **not** introduced now. Keep it as the next escalation candidate if
our needs expand from retrieval shape into semantic prose/style checks such as terminology,
sentence style, paragraph conventions, or richer markup-scoped editorial policy.

Reconsider Vale when one or more of these becomes true:

- several custom prose/terminology rules accumulate;
- multiple repositories need one shared editorial style;
- exceptions and markup-aware semantic scopes become cumbersome in the lightweight checker;
- the custom checker starts reimplementing a general-purpose prose lint framework.

Until then, adding Vale would add another dependency and policy system before we have a
measured need for it.
