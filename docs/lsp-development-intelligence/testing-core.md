# Development Intelligence testing — protocol and lifecycle

| | |
| --- | --- |
| **Status** | Split from the revalidated 2026-09-30 design |
| **Current baseline** | `f1493ee` |
| **Purpose** | Deterministic protocol, dispatcher, lifecycle, cleanup, workspace, document-sync, and process tests |
| **Source index** | `docs/lsp-development-intelligence-testing-2026-09-27.md` |

> Read this file only when its topic is relevant. The project index is
> `docs/lsp-development-intelligence/README.md`.

---

## 1. Test philosophy

Development Intelligence introduces three classes of risk that normal unit coverage alone
will not catch:

1. **protocol/state risk** — LSP is bidirectional, stateful, concurrent, and partially
   asynchronous;
2. **trust/side-effect risk** — a local “analysis” process can still write files or execute
   project code;
3. **product-regression risk** — a private semantic subsystem can consume resources or a
   future public semantic tool can add schema, latency, and model-choice cost even when all
   protocol calls technically succeed.

The test design therefore separates:

- deterministic protocol correctness;
- process/lifecycle correctness;
- provider-profile safety;
- baseline MCP compatibility;
- semantic quality experiments;
- live real-provider smoke;
- performance/resource gates.

A real language server must **not** be required for the normal test suite.

The normal suite must be able to simulate every failure mode that matters.

---

### 1.1 Two independent performance questions

Performance testing must answer two different questions and must not mix them.

#### Suite A — standalone provider performance

> If Binnacle did not exist, how fast and accurate is this language server by itself?

This suite speaks LSP directly to the provider process and measures process/project startup,
steady-state semantic requests, resource use, and semantic correctness.

#### Suite B — Binnacle integration performance

> After the same provider is integrated into the MCP server, what additional latency,
> resource cost, failure surface, and quality change does Binnacle add?

This suite calls the real FastMCP/Binnacle path and measures end-to-end behavior plus the
internal phase timings needed to separate provider cost from integration cost.

The primary decision metric is **resident steady-state behavior** because normal use is
expected to reuse long-lived language servers. Cold startup remains measured, but it is a
separate first-use metric rather than the main optimization target.

A performance number is valid only when the operation's semantic result passes its
correctness assertion.

---

## 2. Test-layer map

Recommended layout:

~~~text
tests/
  unit/
    core/
      test_lsp_framing.py
      test_lsp_dispatcher.py
      test_lsp_positions.py
      test_provider_profiles.py
      test_workspace_resolution.py
      test_semantic_normalization.py
      test_diagnostic_normalization.py
    tools/
      test_inspect_symbol.py          # only if that public tool is later approved
      test_check_code.py              # only if that public tool is later approved

  integration/
    lsp_test_server.py                # deterministic fake provider fixture/support
    analyzer_test_support.py
    test_lsp_process.py
    test_lsp_lifecycle.py
    test_lsp_concurrency.py
    test_lsp_shutdown.py
    test_lsp_document_sync.py
    test_lsp_failure_containment.py
    test_lsp_side_effect_policy.py
    test_development_intelligence_lifespan.py
    test_semantic_integration.py
    test_analyzer_execution.py

  contracts/
    test_visibility.py                # existing, extended only if public surface changes
    test_descriptions.py              # existing
    test_development_intelligence_contract.py

  system/
    test_lsp_reload_cleanup.py
    test_lsp_resource_caps.py

  live/
    test_pyright_lsp_smoke.py
    test_pyright_cli_smoke.py
    test_ruff_readonly_smoke.py
~~~

Names can be adjusted to match the final module split, but the layer boundaries should
remain.

---

## 3. Deterministic fake LSP server

This is the most important test asset.

Do not test the protocol core primarily against Pyright. Real providers are too slow,
version-dependent, and difficult to force into rare failure states.

Implement a tiny Python fixture server that speaks stdio JSON-RPC and is controlled by
arguments or environment variables.

### 3.1 Required fake-server behaviors

Normal behavior:

- initialize response with configurable capabilities;
- initialized notification acceptance;
- didOpen/didChange/didClose recording;
- documentSymbol;
- workspace/symbol;
- definition;
- references;
- push diagnostics;
- clean shutdown/exit.

Fault behavior:

- delay initialize;
- never answer initialize;
- exit during initialize;
- exit after initialize;
- exit while a request is pending;
- malformed Content-Length;
- invalid JSON body;
- oversized header;
- oversized body;
- duplicate response ID;
- unknown response ID;
- delayed response after client timeout;
- send multiple frames in one write;
- split one header/body across many writes;
- stderr spam;
- stdout EOF without protocol shutdown.

Server-to-client requests:

- workspace/configuration;
- window/workDoneProgress/create;
- client/registerCapability;
- workspace/applyEdit;
- unknown custom request.

Concurrency behavior:

- two requests complete out of order;
- a slow request does not block a fast response;
- multiple notifications arrive between responses.

### 3.2 Fixture observability

The fake server should write a separate test-control log, not protocol stdout, recording:

- process PID;
- request methods/IDs;
- received document versions/hashes;
- shutdown/exit reception;
- child process PID if one is intentionally spawned;
- whether it attempted a workspace write.

Tests can then assert lifecycle facts without parsing Binnacle telemetry.

### 3.3 Why a fake server is mandatory

It lets the suite prove:

- exact state transitions;
- timeout handling;
- cleanup after malformed output;
- no deadlock from server-to-client requests;
- concurrent request correlation;
- no duplicate provider startup;
- correct late-response handling.

Those cannot be made reliable with a real provider.

---

## 4. Framing/parser unit tests

The framing parser should be tested as a pure state machine.

### 4.1 Valid frame cases

Cover:

- one complete frame;
- header and body arriving byte-by-byte;
- several frames in one read;
- CRLF header separation;
- UTF-8 JSON body;
- notification without ID;
- request/response with integer IDs;
- response with result=null;
- JSON-RPC error response.

### 4.2 Invalid/bounded frame cases

Cover:

- missing Content-Length;
- invalid integer;
- negative length;
- duplicated conflicting Content-Length;
- header over configured maximum;
- body over configured maximum;
- truncated EOF;
- malformed JSON;
- non-object JSON;
- unsupported JSON-RPC version if the client validates it.

Expected result:

> the provider instance fails with a stable internal reason and pending requests are
> resolved as provider failures; no baseline MCP tool failure is induced.

### 4.3 Parser resource gate

Feed adversarial chunks without allowing unbounded buffer growth.

The test should assert a hard maximum retained buffer size.

---

## 5. Dispatcher and request-correlation tests

### 5.1 Request IDs

Test:

- monotonically/uniquely assigned IDs;
- wrap/large value behavior if relevant;
- response routed to correct waiter;
- unknown response ID ignored/logged safely;
- duplicate response cannot complete a waiter twice.

### 5.2 Timeouts

Test:

- request timeout returns a provider timeout result;
- timed-out request is removed from pending state;
- a late response is discarded safely;
- a timeout does not terminate a healthy provider unless policy says so;
- repeated timeouts can transition capability/provider to DEGRADED/COOLDOWN.

### 5.3 Provider exit

When stdout/process exits:

- all pending requests finish exactly once;
- no waiter hangs;
- exit reason is recorded;
- manager removes the dead instance;
- baseline tool fallback remains available.

### 5.4 Server-to-client requests

Test each policy explicitly.

workspace/configuration:

- returns only profile-controlled settings;
- does not expose arbitrary Binnacle configuration/secrets.

workspace/applyEdit:

- is rejected;
- no filesystem mutation occurs.

client/registerCapability:

- safe supported registrations can be accepted if implemented;
- unsupported/write-oriented registrations are rejected.

Unknown request:

- standards-compatible error;
- provider remains usable if it tolerates the error.

---

## 6. Position-encoding tests

Position conversion deserves its own module.

Test files should include:

- ASCII;
- Chinese characters;
- combining marks;
- emoji/non-BMP code points;
- mixed line endings if supported;
- zero-length ranges;
- end-of-line positions.

Required conversions:

- Python code-point index to UTF-16 code units;
- UTF-16 code units back to Python index;
- any negotiated UTF-8/UTF-32 support added later.

Round-trip tests should be property-based where useful.

A definition/reference feature must not ship until non-BMP tests pass.

---

## 7. Lifecycle state-machine tests

### 7.1 Discovery states

Cover:

- provider missing -> ABSENT;
- disabled profile -> DISABLED;
- configured executable invalid -> stable unavailable reason;
- negative discovery cache prevents repeated PATH probing;
- cache expiry allows later discovery.

### 7.2 Startup states

Cover:

- ABSENT/discoverable -> STARTING -> READY;
- initialize timeout -> COOLDOWN;
- process crash -> COOLDOWN;
- retry after cooldown;
- explicit disable prevents retry.

### 7.3 Single-flight startup

Launch many concurrent callers for the same workspace/profile.

Assert:

- exactly one process starts;
- all eligible callers observe the same instance;
- failures are distributed consistently;
- no deadlocks.

### 7.4 Instance limits

With max_instances=N:

- N workspaces can be resident;
- N+1 follows the chosen eviction/refusal policy;
- an active/in-flight instance is not evicted unsafely;
- LRU/idle order is deterministic.

### 7.5 Settling behavior without a second lifecycle state

Using the fake provider, simulate:

- READY but first workspace-symbol request slower than the private semantic-request deadline;
- another operation such as documentSymbol returning quickly;
- repeated workspace-symbol later becoming fast while the same process remains resident.

Assert:

- process state remains READY throughout;
- the slow private semantic request times out without damaging the provider;
- no existing six-tool result depends on that request;
- later requests can succeed without restart or rediscovery;
- latency/timeout telemetry records the settling event rather than mutating a second
  capability-state machine.

---

## 8. FastMCP lifespan and process cleanup tests

### 8.1 Normal shutdown

Start Binnacle test server/lifespan, lazily create an LSP instance, then close lifespan.

Assert:

- shutdown request observed;
- exit notification observed;
- provider process gone;
- child process group gone;
- manager registry empty.

### 8.2 Provider ignores shutdown

Fake provider ignores shutdown/exit.

Assert Binnacle escalates:

1. graceful deadline;
2. TERM;
3. KILL.

No process remains.

### 8.3 Uvicorn-style reload

System/integration test should simulate the relevant server lifespan teardown/startup
sequence.

Assert:

- old provider dies before or during old lifespan completion;
- new lifespan does not reuse stale process state;
- repeated cycles do not accumulate provider processes.

### 8.4 Abrupt process-tree case

Fake provider spawns a child and then hangs.

Assert process-group cleanup kills both parent and child.

This is a release gate, not optional polish.

---

## 9. Workspace and path-policy tests

Cover:

- path inside default root;
- path inside /tmp;
- path outside allowed roots;
- symlink escaping an allowed root;
- file path and directory path;
- Git worktree root;
- nested Git worktree/submodule if supported;
- non-Git project marker fallback;
- ambiguous/multiple project markers.

Provider command discovery tests:

- service-PATH executable found;
- missing executable;
- explicit trusted absolute command;
- .venv/bin executable present but **not auto-selected**;
- node_modules/.bin executable present but **not auto-selected**;
- repository editor config naming a command is ignored;
- project wrapper script is ignored unless explicitly configured.

---

## 10. Document-synchronization tests

### 10.1 Open

First semantic operation:

- reads authoritative disk content;
- sends didOpen once;
- correct language ID;
- version starts deterministically.

### 10.2 No change

Second operation with unchanged content:

- no redundant didChange if policy uses hashes;
- returned semantic request uses the same document version.

### 10.3 External change

Modify file outside the manager.

Next position-sensitive operation must:

- detect changed content;
- send didChange before semantic request;
- increment version;
- use new text.

### 10.4 Replacement/rename edge cases

If relevant:

- delete/recreate file;
- file becomes binary/non-text;
- file moves outside allowed root;
- provider instance eviction causes didClose.

### 10.5 No unsaved-editor semantics

Tests should enforce that there is no API for an arbitrary unsaved buffer in v1.

Disk remains authoritative.

---
