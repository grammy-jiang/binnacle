# Python 3.14 glob character-class compatibility — 2026-09-19

## Scope

This maintenance round addresses the differential failure discovered while
validating the 2026-09-19 `search_text` result-budget work: on Python 3.14,
`paths.full_match("a", "[^]")` raised `ValueError` while
`PurePosixPath("a").full_match("[^]")` returned `False`. `full_match` is the
Python 3.10–3.12 compatibility implementation used by the glob filtering in both
`list_files` and `search_text`, so a version-specific mismatch is a tool behavior
problem rather than an isolated test failure.

## Root cause

Character-class translation is deliberately delegated to `fnmatch.translate()`
because the stdlib handles reversed ranges, literal `^`, `!` negation, `]`,
dash/backslash escaping and malformed-class quirks. Binnacle then unwraps the
stdlib's DOTALL regex wrapper to obtain only the class fragment.

Python 3.13 emits wrappers ending in `\Z`, for example:

```text
(?s:[\^])\Z
```

Python 3.14 changed the terminal anchor to `\z`:

```text
(?s:[\^])\z
```

The old `_TRANSLATED` regex accepted only the `\Z` wrapper. On Python 3.14
that made `_class_regex()` treat every translated class as an unknown wrapper and
fall back to raw `[{inner}]` construction. `[^]` was merely the first Hypothesis
example to expose the wider loss of stdlib semantics.

## Impact measurement

A bracket-focused deterministic probe generated 4,324 patterns and compared eight
paths, for **34,592 Python 3.14 comparisons** against `PurePosixPath.full_match`.
Before the fix:

- **7,096 mismatches**;
- **4,333** cases where the stdlib returned a boolean but binnacle raised
  `ValueError`;
- the remainder were incorrect boolean results.

This establishes that the issue affected the character-class compatibility layer
broadly, not just `[^]`.

## Decision and implementation

Do not special-case any individual glob. Replace wrapper recognition with the
small string-based `_unwrap_fnmatch_translation()` helper. It accepts both
stdlib wrapper suffixes, `)\Z` and `)\z`, and returns the enclosed regex body.
Using string suffixes instead of compiling `\z` is intentional: Python 3.10–3.13
need to execute the compatibility code even though their regex engines do not
recognize the Python 3.14 `\z` anchor.

If a future Python version changes the wrapper to an unknown format, the existing
fallback remains in place; the differential property test on Python 3.13+ should
expose that change.

## Regression coverage

The existing Hypothesis differential test remains the main semantic oracle on
Python 3.13+. `[^]` is now also a deterministic `@example`. Additional fixed cases
cover literal `^`, `!` negation, leading `]`, reversed ranges, dash/backslash
escaping and unterminated classes. A direct helper test proves both `\Z` and
`\z` wrappers can be unwrapped on every supported Python version.

Both real consumers have regression tests:

- `list_files(..., glob="[^]")` selects a file literally named `^` and not `a`;
- `search_text(..., glob="[^]")` applies the same filter to content matches.

## Validation so far

Targeted `test_properties.py`, `test_list_files.py`, and `test_search_text.py`:

- Python 3.10: 59 passed, 1 skipped (no stdlib `PurePath.full_match` reference);
- Python 3.11: 59 passed, 1 skipped;
- Python 3.12: 59 passed, 1 skipped;
- Python 3.13: 60 passed;
- Python 3.14: 60 passed.

The same 34,592-case Python 3.14 exhaustive probe that produced 7,096 mismatches
before the change now produces **0 mismatches**.

Full-project validation, with a separate job spool for each interpreter:

- Python 3.10: **570 passed, 1 skipped**, coverage 88.34%;
- Python 3.11: **570 passed, 1 skipped**, coverage 88.34%;
- Python 3.12: **570 passed, 1 skipped**, coverage 88.37% on the clean rerun;
- Python 3.13: **571 passed**, coverage 88.31%;
- Python 3.14: **571 passed**, coverage 88.29%.

The 3.12 matrix's first pass reproduced the repository's existing
`test_concurrent_stops_agree` race: one of two concurrent `stop_job` calls briefly
lost the job record. The same test immediately passed alone, and the complete 3.12
suite then passed on rerun. The failure has no dependency on paths/glob code and is
not attributed to this change.

## Production integration

The verified change was copied to the live `binnacle` tree on 2026-09-19 only
after every existing target file matched the research snapshot baseline byte-for-byte.
A rollback copy was created at
`/tmp/binnacle-before-py314-glob-20260919T112220`. WatchFiles performed one normal
reload and the live targeted suite passed 60/60. No MCP tool signature or
description changed, so no connector schema refresh was required.

A real ChatGPT `openai-mcp` checkpoint used `/tmp/binnacle-glob-live` containing
two files, `^` and `a`, both with the text `needle`. `list_files` with
`glob="[^]"` returned exactly `/tmp/binnacle-glob-live/^`. `search_text` for
`needle` with the same glob also returned exactly that file at line 1. This
confirms the corrected character-class semantics through both production MCP
consumer paths, not only the helper/property tests.

## Full-project validation

The full suite was then run on every supported interpreter with an isolated job
spool per version:

- Python 3.10: **570 passed, 1 skipped**, coverage 88.34%;
- Python 3.11: **570 passed, 1 skipped**, coverage 88.34%;
- Python 3.12: **570 passed, 1 skipped**, coverage 88.37% on the clean rerun;
- Python 3.13: **571 passed**, coverage 88.31%;
- Python 3.14: **571 passed**, coverage 88.29%.

The expected skip on 3.10–3.12 is the differential test itself because those
stdlib versions do not yet provide `PurePath.full_match`. The first Python 3.12
full run hit the repository's known `test_concurrent_stops_agree` race; that test
passed immediately in isolation and the complete 3.12 suite passed on rerun. It
has no dependency on `paths.full_match`.
