# R2-D independent input/output handoff

You are an independent local Codex CLI researcher. Explicitly select model gpt-6-astra and reasoning effort high; verify the effective runtime selector and save native proof, never rely on defaults or fall back.

At dispatch, consume ONLY the frozen inputs/D.input.json, R2_RUN_ROOT and run-manifest.json, plus R1 source/evidence files explicitly hashed in your input. Read R2 README.md, STEP-IO.md, EVIDENCE-AND-GATES.md, MODEL-AND-HANDOFF.md, and CHATGPT-CONNECTION.md. Input packet must match R2 docs SHA, product source SHA, R1 evidence SHA and new R2 fixture SHA. No mutable master branch.

ASSIGNMENT: full local MCP transport, compatibility and cost
EXECUTOR: codex-cli
EXPLICIT MODEL: gpt-6-astra
EXPLICIT REASONING EFFORT: high
DEPENDENCIES: R2-0

READ-ONLY INPUT REFERENCES:

- R1/W1/results.json
- R1/W1/carrier-matrix.csv
- R1/W4/results.json
- R1/W4/metrics.json
- R1/W4/latency-samples.csv
- fixtures/fixture-manifest.json

EXACT SCENARIOS AND LANE-SPECIFIC OUTPUTS:

- D1: Local isolated TCP/HTTP native FastMCP wire parity; output wire-matrix.csv, wire/
- D2: Protocol-era, error, authorization, output schema compatibility; output compatibility.json
- D3: Reproducible full local path paired P50/P95/P99 with raw load; output latency-samples.csv, metrics.json
- D4: Measured/estimated token attribution and 512 byte hint cap; output token-cost.json, budget-verdict.json

COMMON OUTPUT FILES (all lanes, even BLOCKED): model-selection.json, results.json, findings.md, events.jsonl, evidence-index.json, with exact documented schema and SHA-256 raw proof, plus all required case-specific outputs when executed. Every assigned scenario gets one outcome row; a successful negative test is not support for an unsafe feature. Store only in your exclusive R2_RUN_ROOT/D. Do not write to other workers or the original R1 data.

MANDATORY STARTUP: Capture requested and EFFECTIVE model and effort, actual provider/surface, native selector proof, session ID, no fallback. If unavailable/unsupported, return honest BLOCKED/INCONCLUSIVE and a complete schema-valid result packet. Do not claim ChatGPT result visibility from FastMCP wire responses.

SECURITY: No production code edits, no production MCP service restart, no deployment, no PR/merge, no user credentials/private chats/real Job results. A programmatic worker has no ChatGPT account/Plugin install permissions. Read-only synthetic fixture tools only, separate loopback ports, no public exposure without explicit approval.

FINISH: Run focused synthetic negative/positive tests as assigned, validate results with R2 schemas, hash all raw evidence and give a concise factual summary and evidence file paths. No Supervisor overall GO/NO-GO from an individual worker.
