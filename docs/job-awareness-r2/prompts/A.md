# R2-A independent input/output handoff

You are an independent local Codex CLI researcher. Explicitly select model gpt-6-sol and reasoning effort medium; verify the effective runtime selector and save native proof, never rely on defaults or fall back.

At dispatch, consume ONLY the frozen inputs/A.input.json, R2_RUN_ROOT and run-manifest.json, plus R1 source/evidence files explicitly hashed in your input. Read R2 README.md, STEP-IO.md, EVIDENCE-AND-GATES.md, MODEL-AND-HANDOFF.md, and CHATGPT-CONNECTION.md. Input packet must match R2 docs SHA, product source SHA, R1 evidence SHA and new R2 fixture SHA. No mutable master branch.

ASSIGNMENT: independent genuine ChatGPT test connection capability
EXECUTOR: codex-cli
EXPLICIT MODEL: gpt-6-sol
EXPLICIT REASONING EFFORT: medium
DEPENDENCIES: R2-0

READ-ONLY INPUT REFERENCES:

- R1/W1/results.json
- R1/W1/carrier-matrix.csv
- R1/S0/connection-evidence.json
- docs/job-awareness-feasibility/DESKTOP-OPERATOR.md
- fixtures/fixture-manifest.json

EXACT SCENARIOS AND LANE-SPECIFIC OUTPUTS:

- A1: Official Plugin/secure tunnel routes, permissions and available/blocked verdict; output connection-options.json
- A2: Isolated read-only mock tool/schema and native local nonce call; output synthetic-app.json, local-canary.json
- A3: Separate endpoint/auth proof, exact external permission blocker; output transport-evidence.json, account-action-required.json
- A4: Real ChatGPT Chat E1 plugin nonce handoff and gate; output chat-handoff.json

COMMON OUTPUT FILES (all lanes, even BLOCKED): model-selection.json, results.json, findings.md, events.jsonl, evidence-index.json, with exact documented schema and SHA-256 raw proof, plus all required case-specific outputs when executed. Every assigned scenario gets one outcome row; a successful negative test is not support for an unsafe feature. Store only in your exclusive R2_RUN_ROOT/A. Do not write to other workers or the original R1 data.

MANDATORY STARTUP: Capture requested and EFFECTIVE model and effort, actual provider/surface, native selector proof, session ID, no fallback. If unavailable/unsupported, return honest BLOCKED/INCONCLUSIVE and a complete schema-valid result packet. Do not claim ChatGPT result visibility from FastMCP wire responses.

SECURITY: No production code edits, no production MCP service restart, no deployment, no PR/merge, no user credentials/private chats/real Job results. A programmatic worker has no ChatGPT account/Plugin install permissions. Read-only synthetic fixture tools only, separate loopback ports, no public exposure without explicit approval.

FINISH: Run focused synthetic negative/positive tests as assigned, validate results with R2 schemas, hash all raw evidence and give a concise factual summary and evidence file paths. No Supervisor overall GO/NO-GO from an individual worker.
