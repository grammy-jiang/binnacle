# Configurable tokenizer telemetry — 2026-09-21

## Goal

Replace chars/4 as the only result-token size signal with an optional tokenizer-backed
measurement suitable for the server's dominant ChatGPT/OpenAI traffic, while retaining
`est_tokens` unchanged for historical comparability.

The new measurement is deliberately payload-scoped. It counts each MCP result text
block plus the compact `structured_content` JSON with the configured tokenizer. It
does not claim to be the complete ChatGPT request, context-window, or billing count.

## Configuration

Repository default:

```toml
[telemetry.tokenizer]
enabled = false
encoding = "o200k_base"
client_prefixes = ["openai-mcp"]
```

A deployment enables it in `~/.config/binnacle/config.toml` (or the normal configured
TOML path). Environment override follows the existing nested settings convention, for
example `BINNACLE_TELEMETRY__TOKENIZER__ENABLED=true`.

When a client matches `client_prefixes`, a ready tokenizer adds two fields to the
existing `tool_result` line:

```text
tokenizer_tokens=72 tokenizer_encoding=o200k_base
```

The old `est_tokens=chars/4` field remains unchanged.

## Availability and failure policy

Tokenizer telemetry must not become part of MCP correctness.

`tiktoken` may fetch an encoding cache on first use, and its upstream HTTP fetch does
not specify a timeout. Therefore Binnacle never performs first-time tokenizer
initialization synchronously in a tool response. Enabling the feature starts a daemon
prewarm thread when the middleware is constructed.

Until the tokenizer is ready, tool results are returned normally and simply omit the
optional tokenizer fields. Loading or counting failures emit one telemetry warning and
do not fail the MCP call.

When the feature is disabled, the implementation does not import `tiktoken` and does
not load an encoding.

## Raspberry Pi resource measurement

Measured on the development Raspberry Pi with Binnacle's real environment:

- package: `tiktoken` 0.14.0; installed package directory about 3.6 MiB;
- Binnacle process RSS with telemetry disabled: about 86 MiB;
- Binnacle process RSS after enabled `o200k_base` prewarm: about 162 MiB;
- observed incremental RSS: about 76 MiB.

Encoding throughput after warm-up:

| Payload chars | `o200k_base` tokens | p50 | p95 |
| ---: | ---: | ---: | ---: |
| 512 | 134 | 0.042 ms | 0.043 ms |
| 4,096 | 1,064 | 0.300 ms | 0.311 ms |
| 16,384 | 4,586 | 1.384 ms | 1.414 ms |
| 65,536 | 18,350 | 5.556 ms | 5.859 ms |

The CPU cost is small relative to normal MCP/model round trips; memory is material
enough to justify the explicit opt-in switch.

## Live local checkpoint

With the feature enabled and an in-memory client named `openai-mcp(ChatGPT)`, a real
`list_files` call produced:

```text
event=tool_result ... content_chars=39 structured_bytes=196 est_tokens=58 tokenizer_tokens=72 tokenizer_encoding=o200k_base ...
```

The tokenizer had already emitted `event=tokenizer_ready encoding=o200k_base`.

With the feature disabled, importing the Binnacle server left `tiktoken` absent from
`sys.modules`.

## Validation

- focused tokenizer/config/logging tests: 30 passed;
- full suite under repository-default hermetic config: 863 passed, 3 skipped.

The change is developed separately from the single-job `job_status` command-preview
A/B so the two optimizations can be reviewed and rolled back independently.
