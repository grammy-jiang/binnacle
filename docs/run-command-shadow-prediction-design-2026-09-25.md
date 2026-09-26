# run_command shadow prediction design — 2026-09-25

Status: implementation design for an owner-requested shadow-only experiment. This experiment does not change dispatch behavior.

## 1. Goals and invariants

The experiment predicts whether a `run_command` dispatch will finish in one of three runtime buckets:

- `short`: runtime < 10 s
- `medium`: 10 s <= runtime <= 60 s
- `long`: runtime > 60 s

Three predictors run independently:

1. `memory`: exact command hash first, then command-shape history.
2. `rules`: deliberately small hand rules derived from measured local evidence.
3. `judge`: an asynchronous Cerebras classifier used only for unsupported, complex commands.

The experiment is strictly shadow-only. Explicit `background=true`, explicit `background=false`, the existing automatic regex policy, bounded foreground waits, warm-up semantics, job ownership, MCP schemas and result payloads are unchanged. Prediction is performed only after the dispatch plan has been decided and never feeds that plan.

Repository defaults disable the whole feature and every predictor. Deployment enablement is local configuration only.

## 2. Evidence basis and privacy contract

The measured 2026-09-11 through 2026-09-25 dataset contains 16,728 terminal runtimes. 13.23% exceed 10 s and 4.62% exceed 60 s. Out-of-sample results favor a 60 s exact/shape memory table; the measured memory predictor reaches F1 0.489 at 60 s with AUC 0.855 and direct exact/shape support for 54.2% of test calls. The current 500-character argument clip makes the first token unrecoverable for 40.99% of historical calls, so every feature used by this experiment is computed from the full command inside `run_command` before middleware clipping.

The local rule-mining analysis found only one incremental lexical family that clears the proposed add gate: an explicit numeric `sleep N` with N >= 10 s. Broad Python, `uv run`, Git, test-runner, heredoc-length and wait-threshold rules remain challengers only through memory/judge evidence, not promoted hand rules.

The journal remains privacy-safe:

- no raw command text;
- no deployment-local regex text;
- no sanitized judge prompt;
- no secret-bearing environment values;
- only hashes, closed-vocabulary classes, scalar features, predictor outputs and error classes.

A sanitized judge prompt may be retained only in the private prediction evidence directory when private retention is enabled. It never enters ordinary journald telemetry.

## 3. Feature model

Features are built from the full command before request-argument clipping.

Required derived fields:

- full SHA-256 command hash;
- shape key and a SHA-256 prefix of that shape key;
- first effective token after stripping common prefixes such as `cd ... &&`, `env`, shell `set -euo pipefail`, `timeout`, and `sudo`;
- first-token class from the closed vocabulary `python|uv|pytest|git|shell-builtin|script-path|other`;
- long-runner flags for pytest, tox, pre-commit, uv run/sync/tool, pip, apt, npm, cargo, make, git push/fetch/clone/pull, gh run watch, curl/wget, rsync, tar, find, journalctl -f, sleep N, timeout N, systemctl, docker and ssh;
- largest explicit numeric delay in seconds;
- heredoc presence;
- source length in characters;
- chained-command count;
- declared `wait_seconds`, `background` and `tail_lines`.

The shape key is privacy-preserving and stable enough for local generalization: token class + runner flags + delay bucket + heredoc bit + command-length bucket + chain-count bucket + declared execution-shaping arguments. It excludes raw arguments and literal strings.

## 4. Predictor contracts

All predictors return a bucket, a p90 estimate in seconds, and predictor-specific metadata. A missing prediction is an explicit abstention, not a fabricated prior.

### 4.1 Memory predictor

The memory store is a bounded local JSON file under:

`~/.local/state/binnacle/run-command-prediction/memory.json`

The directory is mode 0700 and the file is mode 0600. Rows are keyed by full command hash and shape key. Each key retains only a bounded recent sample of terminal runtimes; the store also has a bounded number of keys and uses atomic replacement.

Lookup order:

1. exact command history when sample count >= `min_samples`;
2. shape history when sample count >= `min_samples`;
3. abstain.

Prediction uses the empirical p90. Bucket selection follows that p90: <10 s short, <=60 s medium, >60 s long. The journal records only the sample count and whether the source was `exact`, `shape` or `none`.

The run-command hook submits terminal runtime persistence immediately for synchronous completions to the bounded shadow executor, keeping persistence I/O off the response path. Background jobs do not gain a new waiter solely for this experiment; their terminal outcome remains available in `job_exit` and is used by stats/offline evidence. This preserves the existing one-waiter ownership design and keeps shadow instrumentation from creating operational work.

### 4.2 Hand-rule predictor

Rules are deterministic and intentionally conservative. The initial evidence-backed rule set is:

- `sleep_ge_10`: an explicit executed-style `sleep N` with numeric N >= 10 s predicts at least `medium`, p90=N.

Additional simple structural rules may report a bucket only when directly encoded by explicit delay semantics (for example an explicit `timeout N` establishes an upper-bound feature but is not treated as proof of long runtime). Broad lexical presence is never promoted to a long prediction by itself.

The event records stable rule IDs only, never regex text.

### 4.3 Cerebras judge

The judge uses the OpenAI-compatible Cerebras endpoint. The owner-measured key can use only `gpt-oss-120b`; other tested model IDs returned 404 and `/v1/models` returned 403. The API key comes from `CEREBRAS_API_KEY` or a configured 0600 key file. It is never logged. Strict `response_format` JSON-schema output is supported and required by this implementation. Measured calls with local evidence use about 350 prompt plus 90 completion tokens and complete in roughly 330–450 ms end to end.

The filter must pass all gates before a call is queued:

1. judge enabled;
2. memory has fewer than `min_samples` for both exact and shape;
3. command is complex: heredoc, or chain count greater than `complex_chain_threshold`, or source length greater than `complex_length_threshold`;
4. process-local request budgets have capacity for the minute, hour, and day windows;
5. no unexpired cache entry or identical in-flight request exists for the exact command hash.

The measured key limits are 5 requests/minute, 150/hour, 2,400/day, 30,000 tokens/minute, and 1,000,000 tokens/day. Defaults reserve headroom at 4 requests/minute, 120/hour, and 2,000/day. Cache entries are keyed by full command hash and expire by TTL. Identical in-flight requests are coalesced so they share one provider call. A provider HTTP 429 pauses new judge calls until the reset interval from the rate-limit headers; if no usable reset is supplied, the fail-open fallback pause is 60 seconds.

The network call runs in a bounded `ThreadPoolExecutor` after the dispatch plan is fixed. The default timeout is 800 ms. Any timeout, transport failure, parse error, HTTP error or shutdown state is swallowed, reduced to a stable error class, and recorded only in the judge-result event. It can never fail the tool call or alter dispatch.

The prompt contains only:

- the sanitized command;
- host facts: Raspberry Pi 5, 4 cores;
- the shape class;
- local exact/shape sample count and p50/p90 when available;
- the required JSON schema.

The response must satisfy the strict JSON schema with only `bucket` and `p90_s`. Any malformed or non-conforming response is a parse error.

## 5. Sanitizer

Sanitization is performed before prompt construction. It:

- redacts Bearer and Authorization values;
- redacts values next to key/token/password/secret/credential names;
- redacts long `KEY=value` environment assignments;
- redacts base64-like and hex-like blobs longer than 20 characters;
- replaces absolute home paths with `~`;
- redacts email addresses;
- collapses long quoted literals;
- normalizes whitespace;
- caps the sanitized command to a configurable character limit chosen to remain within a few hundred prompt tokens.

The sanitizer is fail-closed for content: if sanitization itself fails, the judge is skipped. Raw and sanitized command text are both absent from the normal journal.

## 6. Telemetry schema

Telemetry is a dataset contract, not debug logging. Field order is fixed.

One line is emitted per dispatch immediately after the existing dispatch decision:

```text
event=run_command_prediction schema=1 call=<id> feature_hash=<12hex> shape_hash=<12hex> first_token_class=<class> heredoc=0|1 chain_n=<n> max_delay_s=<n> len_chars=<n> declared_wait_s=<n> declared_background=none|true|false auto_rule=<rule_hash|-> memory_bucket=short|medium|long|- memory_p90_s=<n|-> memory_n=<n> memory_source=exact|shape|none rules_bucket=short|medium|long|- rules_p90_s=<n|-> rules_hits=<ids|-> judge=queued|cached|skipped|disabled judge_skip_reason=history|fast_shell|fast_git_read|fast_file_read|budget|- judge_cache=hit|miss|-
```

If the judge finishes later, exactly one result line is emitted:

```text
event=run_command_prediction_judge schema=1 call=<id> model=<model> bucket=short|medium|long|- p90_s=<n|-> latency_ms=<n> prompt_tokens=<n|-> completion_tokens=<n|-> error=<class|->
```

A run-command configuration record establishes experiment identity:

```text
event=tool_config tool=run_command shadow_prediction=on|off predictors=memory,rules,judge judge_model=<model|-> filter_hash=<12hex> sanitizer_hash=<12hex>
```

Because this worker does not own the central `server.py` startup logger, the owned run-command module emits this configuration record once per process from the shadow engine initialization path. It is still process-start configuration telemetry and uses the same `tool_config` schema consumed by stats.

All values are whitespace-free. Command, regex and prompt text never appear.

## 7. Stats and offline evidence

`binnacle stats` joins `run_command_prediction` and `run_command_prediction_judge` by `call`, then joins the call to actual runtime using the existing dispatch/result/job lifecycle correlation. Judge lines may arrive after the terminal outcome; event order is therefore not used as a join condition.

The `predictions` section reports:

- window and latest shadow configuration/filter hash;
- dispatch count;
- per predictor coverage;
- at 10 s and 60 s: TP/FP/TN/FN, precision, recall and F1;
- predicted-bucket versus actual-bucket calibration matrix;
- judge latency p50/p95;
- judge errors by class;
- cache-hit rate;
- judge skip reasons;
- memory sample-count distribution and store-size telemetry when present.

The JSON form exposes the same structured fields. Joined export rows contain only call ID, hashes/classes, predictor outputs and actual runtime bucket/seconds; no command text or prompt text.

## 8. Configuration

Repository defaults are fully disabled. The owner can enable the experiment locally with:

```toml
[run_command.shadow_prediction]
enabled = true
predictors = ["memory", "rules", "judge"]
memory_min_samples = 2
memory_max_keys = 4096
memory_samples_per_key = 32
judge_enabled = true
judge_model = "gpt-oss-120b"
judge_timeout_ms = 800
judge_minute_budget = 4
judge_hour_budget = 120
judge_day_budget = 2000
judge_cache_ttl_s = 86400
judge_complex_chain_threshold = 2
judge_complex_length_threshold = 800
sanitized_command_max_chars = 1200
```

The API key remains outside TOML in `CEREBRAS_API_KEY`, or may be supplied through a configured 0600 key file.

## 9. Failure and rollout policy

The shadow engine is best-effort:

- no prediction exception escapes into `run_command`;
- no judge timeout delays the request path;
- memory-store corruption resets the local cache rather than failing dispatch;
- cache/store writes are atomic and permission-restricted;
- a disabled feature performs no external I/O;
- tests use a fake judge transport and never access the network.

This experiment produces evidence only. Any future use of a prediction to alter wait/background behavior requires a separate owner decision and a new design/review.

## 10. 2026-09-26 data-quality check

The first deployed evaluation window contained 1,473 dispatches, all joined to
terminal runtimes. Fifty-nine ran for at least 10 seconds and 21 ran for at
least 60 seconds. There was no duplicate prediction per call, no prediction
exception, and no raw command text in any journal line.

Two selection defects were found and corrected:

- The hand rule missed all four real sleeps of at least 10 seconds because the
  duration regex required whitespace or end-of-string after the number. The
  rule now recognizes shell separators and grouping/quoted command boundaries,
  `do`/`then`, `s` and `m` suffixes, and Python `time.sleep(...)`.
  `timeout` durations and `--timeout` options remain excluded from the
  sleep rule.
- The judge's old `simple` gate skipped 32 of the 59 long runs, including all
  five longest runs (1,192-10,756 seconds), whose first-token class was
  `other`; only 23 of the 59 long runs received any prediction. Short
  commands that can launch long work are now judge-eligible within the
  existing budget. Only clearly fast shapes are skipped, with explicit
  reasons `fast_shell`, `fast_git_read`, and `fast_file_read`.

`binnacle stats --predictions-csv PATH` now exports the existing privacy-safe
joined rows for 7-day, 14-day, and scheduled evaluations without raw command
or prompt text.

The Cerebras judge prompt is now an explicit, versioned contract. Version
`2026-09-26.1` defines wall runtime, bucket boundaries, the `p90_s` meaning,
the Raspberry Pi 5 execution environment, evidence precedence, concrete tool
anchors, the 14-day 87%/9%/4% base rate, and redaction semantics. The system
prompt is about 277 tokens by the conservative characters/4 estimate, below
the 450-token target. Its SHA-256-derived `prompt_hash` is logged on every
judge result and is part of the cache key, so an answer from an older prompt
cannot be reused.

The strict response schema now includes confidence from 0 to 1 and a closed
reason-code vocabulary. Both values are journalled without free text; stats
report confidence deciles and reason counts, and joined CSV/JSONL exports carry
the same fields. The configured default remains 2,000 calls/day, but the judge
engine clamps the effective daily budget to 800 calls (1,200 fewer) so the
expanded prompt, request metadata, and completion remain inside the 800k-token
daily operating envelope against the provider key's 1M-token limit. Tests use
only the fake transport, including malformed-response and prompt-hash cache
regressions.

There were 21 judge timeouts among 492 calls at the deployed 3,000 ms timeout;
observed p95 judge latency was 2,478 ms. No code timeout change is made here:
the deployment owner will raise the host configuration to 5,000 ms.
