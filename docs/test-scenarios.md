# Test scenario matrix

This matrix is the user-scenario and failure-mode complement to the per-module
coverage gate. Branch coverage answers "which code paths ran"; this document
answers "which real workflows and failures are deliberately represented".

A scenario is considered covered only when the test crosses the lowest useful
real boundary. Pure formatting or parsing details may stay unit-level, but
authentication, MCP sessions, durable jobs, configuration loading, packaging,
system observations, and deployment smoke tests must use their real boundary.

## MCP connection, authentication, and client surface

| Scenario | Layer | Primary tests |
| --- | --- | --- |
| Valid bearer token initializes a session and lists tools | HTTP integration | `test_auth_asgi.py` |
| Missing/wrong/doubled bearer token is rejected | HTTP integration | `test_auth_asgi.py` |
| Missing session ID returns 400; unknown/expired ID returns 404 | HTTP integration | `test_auth_asgi.py` |
| Unrestricted client sees the complete surface | Contract / HTTP | `test_protocol.py`, `test_http_workflows.py` |
| ChatGPT sees only its configured six tools | Contract / HTTP | `test_visibility.py`, `test_http_workflows.py` |
| Calling a hidden ChatGPT tool is an MCP tool error | Contract / HTTP | `test_visibility.py`, `test_http_workflows.py` |
| Required args, numeric limits, wrong types, and unknown args are rejected | Contract | `test_input_validation.py` |
| Unknown tool is a protocol error | Contract | `test_protocol.py` |
| X-Request-Id and hashed OpenAI session reach tool-result logs | HTTP integration | `test_http_workflows.py` |

## File browsing, reading, searching, and editing

| Scenario | Layer | Primary tests |
| --- | --- | --- |
| write -> read -> edit -> search -> list complete workflow | HTTP integration / contract | `test_http_workflows.py`, `test_protocol.py` |
| Relative/absolute paths and allowed-root enforcement | Unit / integration | tool unit suites, `test_jobs.py` |
| Direct outside-root path is rejected over MCP | HTTP / contract | `test_http_workflows.py`, `test_protocol.py` |
| Symlink escape outside allowed roots is rejected over MCP | Contract | `test_protocol.py` |
| Missing file, directory-vs-file, binary/lossy text, BOM/CRLF, Unicode | Unit | read/edit/write suites |
| Exact edit, delete-via-empty, replace-all, ambiguous/no-match errors | Unit / contract workflow | `test_edit_file.py`, `test_protocol.py` |
| Glob behavior, hidden/gitignored files, rg missing/timeout/error | Unit | `test_list_files.py` |
| Regex/fixed search, invalid regex, file-as-path, result count/byte budgets | Unit / integration | `test_search_text.py`, indexed-context integration |

## Shell commands and durable jobs

| Scenario | Layer | Primary tests |
| --- | --- | --- |
| Synchronous success/nonzero/signal, merged stderr, stdin, workdir | Integration | `test_jobs.py`, `test_jobs_lifecycle.py` |
| Slow command hands off to durable job; explicit background returns quickly | Integration / HTTP | job suites, `test_http_workflows.py` |
| status wait, timeout, tailing, quiet flag, process listing | Integration | `test_jobs_lifecycle.py`, `test_jobs.py` |
| stop sends TERM then KILL when required and covers the process group | Integration | `test_jobs_lifecycle.py` |
| already-exited/double/concurrent stop is idempotent | Integration / state-machine | lifecycle suite, `test_jobs_state_machine.py` |
| malformed metadata, missing log, PID reuse, server-reload orphan | Integration | lifecycle/store suites |
| concurrent starts/prunes/readers do not corrupt the store | Integration concurrency | `test_jobs_store.py` |
| randomized start/status/list/stop sequences preserve terminal-state invariants | Model-based integration | `test_jobs_state_machine.py` |
| output truncation preserves full log on disk | Integration | `test_jobs.py` |

## Indexed repository context

| Scenario | Layer | Primary tests |
| --- | --- | --- |
| Explicit @context query returns bounded absolute-path evidence | Integration | `test_indexed_context.py` |
| Exact/fixed search remains exact instead of dispatching to index | Integration | `test_indexed_context.py` |
| Disabled pilot, invalid scope, empty query, non-Git root | Integration failure | `test_indexed_context.py` |
| Concurrent queries on one index are serialized | Integration concurrency | `test_indexed_context.py` |
| LRU eviction and reconcile-disabled behavior | Integration | `test_indexed_context.py` |
| Unexpected query/reconcile failure becomes a clean ToolError + telemetry | Integration fault injection | `test_indexed_context.py` |
| Incremental edit produces the same query result as a clean rebuild | Differential unit | `test_indexed_index.py` |
| Parser/store/query/refresh malformed and edge cases | Unit | indexed core suites |

## Configuration, CLI, startup, and packaging

| Scenario | Layer | Primary tests |
| --- | --- | --- |
| Defaults with no config file | Integration | `test_config_loading.py` |
| Nested TOML settings load | Integration | `test_config_loading.py` |
| Environment overrides TOML | Integration | `test_config_loading.py` |
| Invalid TOML and invalid constrained values fail configuration | Integration failure | `test_config_loading.py` |
| Settings cache changes only after explicit restart/cache clear | Integration | `test_config_loading.py` |
| Watchdog config is separate from core Settings | Integration / architecture | config suite, architecture gate |
| setup dry-run, real write path, foreign-unit refusal | Integration | `test_cli.py` |
| dev/prod mode status/switch/failure | Integration | `test_cli.py` |
| token writer/rotation matches server loader and restarts active pieces | Integration | `test_cli.py` |
| doctor/stats command glue and optional Webmin history | Integration/system | CLI + Webmin suites |
| Missing configured token makes server startup/import fail | Integration failure | `test_packaging_smoke.py` |
| Console entry points and CLI help surfaces exist | Packaging integration | `test_packaging_smoke.py` |
| Built wheel contains runtime modules, py.typed, and both entry points | Wheel artifact integration | `test_wheel_artifact.py` |
| Core/server imports when all watchdog companion imports are blocked | Architecture integration | `test_packaging_smoke.py` |

## Logging and observability

| Scenario | Layer | Primary tests |
| --- | --- | --- |
| request start/success/error carries request/session/client/tool | Integration | `test_logging.py` |
| tool call/result share call ID and expose sizes/outcomes without content leak | Integration | `test_logging.py` |
| HTTP correlation headers are actually visible to middleware | HTTP integration | `test_http_workflows.py` |
| job start/exit lines correlate to tool calls | Integration | `test_logging.py` |
| wrapped journal + newer single-line formats parse and aggregate | Unit/scripts/system | logstats/watchlog suites |
| Webmin history window, malformed lines, permission/sudo fallback | System | `test_webminstats.py` |

## Doctor, uplink, and host observation

| Scenario | Layer | Primary tests |
| --- | --- | --- |
| endpoint token good/stale/missing/auth-not-enforced/nothing-listening | System | `test_doctor_connectivity.py` |
| tunnel inactive/wrong URL/header/config/order/health endpoint | System | `test_doctor_connectivity.py` |
| poller healthy/failing/timeout/recovered/missing log | System | `test_doctor_connectivity.py` |
| no route, partial reachability, wedged active, wedged standby | System | doctor/uplink suites |
| gateway/DNS/TCP probes, fallback resolver, device binding, timeouts | System sockets/fakes | `test_uplink*.py` |
| service/config/token/job/journal/boot failures | System | doctor suites |

## Watchdog operational POC

The watchdog is not a Binnacle product feature. Its tests deliberately remain
host-model/system tests and the architecture gate enforces only the dependency
direction `watchdog -> core`.

Covered scenarios include healthy/no-op, active-route wedge/dead-end failover,
last-route protection, standby repair, restore/flap damping, USB re-enumeration
schedules and reset methods, profile preference/fallback, missing-route recovery,
link-level repair, driver reload, service repair, NetworkManager/supplicant
recovery, pause/dry-run, fast-path failover, tunnel socket affinity, multi-radio
failover, hung-cycle supervision, repair concurrency, logging/replay, and
watchdog CLI success/failure paths. See the split `test_watchdog_*.py` suites.

## Live deployment smoke

`tests/live/test_deployment_smoke.py` is deliberately opt-in and read-only:

```bash
BINNACLE_LIVE=1 uv run pytest tests/live -q
```

It asserts exactly one server user unit is active and performs authenticated
initialize + tools/list against the actually deployed localhost MCP endpoint.
It never restarts services, changes networking, writes configuration, or touches
hardware.

## Intentionally non-default or manual

Some failure modes must not be hidden in the default automated suite:

- physically unplugging/replugging radios, real USB reset, kernel-driver reload,
  and intentional NetworkManager disruption;
- real reboot/boot-persistence tests;
- destructive end-to-end watchdog failover on the development host;
- the external ChatGPT/OpenAI connector path beyond the localhost tunnel;
- long soak/resource-load benchmarks;
- mutation testing, which remains an on-demand semantic-strength audit.

These are not gaps to paper over with unsafe tests. The default suite models the
failure and action boundaries with fakes; live read-only checks are opt-in; truly
destructive validations require an explicit manual maintenance window.
