# Auto-background matching: shell input is not a command

Date: 2026-10-10. Scope: standalone fix based on production `02f4bab`;
**no change to running MCP service or the concurrent OS Stage 1 PR**.

## Actual incident and bounded correction

At 2026-10-10 01:18:35 AEDT, `run_command` for Stage 1 received an automatic
background decision on `pytest` at character offsets `[223,229)` inside a
quoted here-document containing `import pytest`. The shell command itself
also ended with an actual `uv run pytest`: the correct executable occurrence
was at `[2775,2781)`. Therefore this one command *should still have been*
backgrounded; its misidentified first match was **not shown to cause** the
subsequent ChatGPT turn gap. The background process exited 1 after 1.128 s,
and no later `job_status` call consumed its result during that turn.

Deployment-local regexes previously searched all raw `bash -c` script text,
including non-executable here-document bodies, their delimiters, shell
comments, here-string operands, and file redirection operands. The correction
preserves script character offsets for stable telemetry and private evidence,
without modifying the actual command sent to bash or any MCP tool schema:

- First perform an inexpensive raw regex check. No raw match: no lexing cost.
- For a possible match, mask here-document bodies, terminator lines, quoted
  delimiter words, comments, here-string operands, and redirection operands.
- Reapply the configured regexes in the original prefix/rule precedence to
  the equal-length masked source. A real `uv run pytest` following a here-doc
  remains eligible; an `import pytest` written to a source file does not.
- Preserve the original character-offset vocabulary but change the automatic
  matching behavior fingerprint by incrementing its semantics version to 2.
- Keep background controls explicit: `background=true` is always available,
  `background=false` still overrides automatic matching, and the original
  script is executed unchanged.

This is **conservative shell-source filtering**, not a complete Bash parser.
Quoted strings outside these special operands, shell substitutions, functions,
and some unsupported Bash syntax can still make arbitrary custom regexes
ambiguous. A suppressed match means “no automatic rule matched the filtered
text,” **not** that the command is guaranteed short or non-executable. The
correct way to launch a known long nonstandard shell script remains
`background=true`. Do not claim comprehensive shell execution analysis.

## Historical policy replay and performance risk

Source: local private `run-command-evidence` records, bounded to
`2026-10-09T22:00:00Z`; no raw commands or authentication content copied to
this document. These records exist only for auto-matched commands and are not
a random sample of all run_command calls.

- 3,949 existing automatic policy matches re-evaluated under the new code.
- 3,170 first match spans unchanged.
- 247 remain automatic background calls but the matched span moves to code
  that remains visible after input/redirection filtering.
- 532 become regular (nonautomatic) calls, or 13.47% of the sample.
- The real overnight call moves its matched `pytest` span from 223 to 2775,
  **without changing** the true/false auto-background outcome.
- All 532 suppressed calls had matching Job Manager `job_exit` and
  `run_command_dispatch` records. Historical runtime p50 0.118 s, p90 2.846 s,
  p95 10.948 s; 86 ran longer than 1 s, 39 longer than 5 s, 11 longer than
  30 s, 7 longer than 50 s. Based on observed requested foreground caps, the
  **counterfactual additional wait** sums to ~677.2 s across the sample,
  with per-call p90 1.58 s, p95 6.63 s and maximum 49 s. This is not a
  measured live performance improvement or a proof that every suppressed
  match was semantically false.
- Microbenchmarks on ~4k auto-matched records: new match p50 ~0.18 ms,
  p95 ~2.02 ms; nonmatch `git status` path ~0.005 ms. These exclude MCP
  overhead and are advisory only.

Acceptance must consider **correctness and performance**, avoiding a hidden
regression from lengthened synchronous calls. The original automatic command
patterns are deployment-local, not stored as repository defaults.

## Regression plan and rollback boundary

Focused tests cover heredoc-only data, true pytest after an input block,
quoted and tab-stripped delimiters, multiple delimiters, comment filtering,
input/output redirections, here-strings, preserved match offsets,
new semantic policy fingerprint, and a real FastMCP tool request where
`import pytest` is written to a file but no test executable is invoked.

Review normal pre-commit, managed two-lane full tests, coverage policy and
exact-head GitHub CI. Retain a separate source branch; do not alter active
production configuration, deployment refs or the OS Stage 1 worktree.
Production deployment requires the repository's independent review, quiet
window, smoke and rollback procedures. Rule semantics v2 can be rolled back
to the previous tagged implementation/config if necessary.

## Local qualification checkpoint

- New helper has 100% branch-inclusive coverage in the focused
  `tests/unit/core/test_auto_background_shell.py` plus integrated MCP policy
  telemetry tests (39 passing at that checkpoint); mandatory floor is 90%.
- Exactly one new foundational module is added to the existing **strict**
  `application_shell` ownership group in `scripts/gate_a_manifest.py`; no
  architecture waiver or relaxed manifest assertion is used.
- The coverage-policy gate passed: 124 production + 46 script modules,
  zero hard errors. The three preexisting script coverage debts remain.
- Production deployment and live ChatGPT behavior validation are deliberately
  separate gates, not implied by local source qualification.

## Review findings on original source `f1c509d` (2026-10-10)

Independent Codex review reported four valid P2 edge cases; all four were
reproduced with source-level regressions, and the test Bash fragments were
also accepted by `bash -n`:

1. `<<''` and `<<""` are valid, empty quoted delimiters; blank input lines
   terminate those heredocs. Distinguish an absent word from a quoted empty
   word, then preserve subsequent executable commands.
2. `<<$'EOF'` and `<<$"EOF"` remove the dollar-quote prefix. Support the
   common Bash ANSI-C backslash escapes in `$'...'`; for unfamiliar escapes
   retain a conservative unmasked source rather than invent a terminator.
3. Escaped physical newlines extend the logical command line before heredoc
   data starts. Keep pending delimiters while parsing that command's next
   physical line; the actual pipeline/command remains matchable.
4. Correctly consume file operands of compound Bash redirections, including
   `>|`, `>&`, `<&`, `&>` and `&>>`, instead of treating operator suffixes as
   part of a filename.

These modifications preserve the original dispatched script and maintain
original character offsets for evidence and behavior-fingerprint version 2.
The resulting focused shell-matching tests reached **100% branch-inclusive
coverage** after the review repairs. As before, this remains a conservative
filter rather than an exhaustive Bash parser.

## Copilot P2 follow-up on original PR source

Review `4235585444` correctly observed that an ordinary Bash arithmetic
left-shift (`<<`) inside `((...))` or `$((...))` can be misclassified as a
heredoc, hiding all following real executable commands. The follow-up patch
tracks nested arithmetic parentheses across physical lines, masks arithmetic
expression data, and does not create a pending here-document from a shift.
Regression cases include one-line arithmetic, nested arithmetic, multiline
shifts, and mixed real heredoc/arithmetic before executable `pytest`.
The snippets are checked as valid using `bash -n`; the production command
remains byte-identical and the original evidence offsets remain stable.

## Escaped-newline delimiter word review follow-up

Codex `4235614013` identified a valid Bash here-document delimiter assembled
across `<<EO\\` + physical newline + `F`. Policy lexing now assembles these
escaped physical newline command fragments before parsing a here-doc word,
removes the escaped newline from the delimiter value, and preserves its
original source offsets/line count. A continuation pipeline is still parsed
as executable code, not consumed as here-doc data. Dedicated cases verify
both forms with `bash -n` and check that later executable `pytest` is not
hidden. The executed command itself remains byte-identical.

## Operator continuation follow-up

Codex `4235637851` identified valid Bash pipelines and AND-OR lists ending
with `|`, `|&`, `&&`, or `||` where the next physical line is executable code
before the heredoc body. The masker now preserves pending heredocs across
these operator continuations, while distinguishing the `>|` clobber
redirection from a pipe. Regression tests exercise all four operators,
multiple continued lines and the redirection counterexample, using `bash -n`
for shell syntax validity. As in the other cases, the actual Bash command and
its character offsets are unchanged.

## Final Codex P2 correction: comments and double-quoted delimiters

Reviews 4235675544 and 4235675547 on commit aa9a307 identified two more
valid Bash forms requiring exact lexical treatment. First, a backslash at
the end of a shell comment is not a physical-line continuation; a subsequent
real pytest command must remain visible. The continuation check now
distinguishes shell comments, escaped hash literals and quoted hash text,
and rejects single-quoted literal backslashes. Second, a backslash followed
by a physical newline is removed in double-quoted here-document delimiter
words, including CRLF text; later real test commands must not be hidden
behind a permanently unmatched delimiter. Both cases now have Bash-validated
regression fixtures and branch-coverage tests, retaining original command
bytes and character positions.

## Escaped pipeline tokens in shell arguments (Codex P2)

Exact-head independent review of 3bdcf92 reported P2 4235832042:
a literal backslash-escaped pipe at the end of a heredoc declaration line was
being mistaken for a real pipeline continuation, so the following heredoc
body stayed searchable and caused false automatic background selection.
The shell syntax walker now masks escaped pipe/ampersand operator characters
at their original offsets before classifying trailing operator tokens.
Regression tests cover escaped pipe, escaped AND/OR markers, and a genuine
unescaped pipeline following an escaped literal backslash. Bash -n accepts
these fixtures. The command passed to Bash and on-disk job result contracts
remain unchanged.

## Additional Bash comment / pending-heredoc correctness corrections

The independent review of 0c0b702 identified three separate P2 cases
(4235869613, 4235869618, 4235869623):

- When Bash joins a backslash-newline, the shell-visible preceding character,
  not the raw newline, determines whether a following hash begins a comment.
  Both true comment and embedded-word hash cases have regressions.
- A trailing pipeline or AND/OR operator continues waiting for a command
  across comments and blank lines. The pending-heredoc state is preserved
  until a real executable command is parsed.
- Bash removes escaped physical newlines in unquoted heredoc body text before
  matching the terminator. Quoted delimiter words disable this behavior.
  The scanner records quote mode per pending delimiter and joins unquoted
  body lines only for delimiter comparison, while masking the original bytes
  at unchanged offsets.

These changes were tested using valid Bash syntax and harmless Bash execution
fixtures, as well as preserving the existing MCP policy and log contracts.
