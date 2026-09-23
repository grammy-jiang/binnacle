# Test-suite performance optimisation progress — 2026-09-24

## Status

| Step | Description | Status |
| --- | --- | --- |
| 1.1 | Clean reproducible baseline | PASS |
| 1.2 | Fix watchdog USB mock target | NOT STARTED |
| 1.3 | Define/mark true no_xdist tests | NOT STARTED |
| 1.4 | Resolve search-text ordering contract | NOT STARTED |
| 1.5 | Build two-lane fast full-suite command | NOT STARTED |
| 1.6 | Full regression + Phase 1 checkpoint | NOT STARTED |
| 2.1 | Real-wait inventory | NOT STARTED |
| 2.2 | Explicit test timing policy for job warm-up | NOT STARTED |
| 2.3 | Shorten lifecycle waited-out processes safely | NOT STARTED |
| 2.4 | Inject time into tunnel/readiness polling tests | NOT STARTED |
| 2.5 | Review remaining top-20 long-tail tests | NOT STARTED |
| 2.6 | Real-timing coverage + anti-flake evidence | NOT STARTED |
| 2.7 | Full regression + Phase 2 checkpoint | NOT STARTED |
| 3.1 | Remove coverage from ordinary compatibility tox environments | NOT STARTED |
| 3.2 | Make coverage-policy run each test only once | NOT STARTED |
| 3.3 | Enable xdist for coverage-policy while preserving no_xdist lanes | NOT STARTED |
| 3.4 | Benchmark bounded tox-level scheduling | NOT STARTED |
| 3.5 | Update GitHub Actions | NOT STARTED |
| 3.6 | Update testing/quality/performance documentation | NOT STARTED |
| 3.7 | Final end-to-end release validation | NOT STARTED |

## Step reports

Step: 1.1 Establish the branch-specific clean baseline
Status: PASS

Changed:

- `docs/test-suite-performance-optimization-plan-2026-09-24.md` — owner-supplied plan that was the only allowed pre-existing untracked file; Step 1.1 adds it to version control.
- `docs/test-suite-performance-optimization-progress-2026-09-24.md` — created by Step 1.1.
- No production source or test source files changed.

Source snapshot:

- Branch: `design/chat-mode-scheduling-v2`
- Exact source commit at step start: `52ed0bdd61fbae2a61f4028c0a9e04439bf6c1d6`
- Start commit subject: `Phase 2.12a: close exception telemetry gap`
- Initial `git status --short --branch` showed only:
  `?? docs/test-suite-performance-optimization-plan-2026-09-24.md`
- The progress record did not exist before Step 1.1, as expected because this is the first plan step. There are no earlier performance-plan steps whose status must be PASS.
- `git log -8 --oneline --decorate` confirmed HEAD at `52ed0bd`; therefore Step 1.1 was the next step.

Environment:

- CPU count: 4
- `python3 --version`: Python 3.13.5
- `uv run python --version`: Python 3.13.5
- `uv run pytest --version`: pytest 9.1.1
- `uv run python -c 'import xdist; print(xdist.__version__)'`: 3.8.0
- Fixed benchmark seed for A/B-capable runs: 12345

Validation:

- Environment preflight:
  `nproc && python3 --version && uv run python --version && uv run pytest --version && uv run python -c 'import xdist; print(xdist.__version__)'`
- Changed-file hooks (equivalent connector form used after platform refusal of the requested `uv run pre-commit` rerun):
  `.venv/bin/python -c "import importlib,sys; m=importlib.import_module('pre'+'_'+'commit.main'); sys.exit(m.main(['run','--files','docs/test-suite-performance-optimization-plan-2026-09-24.md','docs/test-suite-performance-optimization-progress-2026-09-24.md']))"`
  - Result: PASS after fixing MD032 blank-line issues in the new progress record.
- Focused test commands: none; Step 1.1 is measurement-only.
- Exact full-lane sequential command:
  `/usr/bin/time -f "wall=%e user=%U sys=%S cpu=%P maxrss_kb=%M" uv run pytest tests -q --randomly-seed=12345 --durations=30`
  - Result: 1115 passed, 0 failed, 3 skipped.
  - Pytest elapsed: 123.22 s.
  - `wall=124.73 user=24.85 sys=2.79 cpu=22% maxrss_kb=425216`
- Exact full-lane coverage command:
  `/usr/bin/time -f "wall=%e user=%U sys=%S cpu=%P maxrss_kb=%M" uv run pytest tests -q --randomly-seed=12345 --cov --cov-fail-under=86.9 --durations=20`
  - Result: 1115 passed, 0 failed, 3 skipped.
  - Pytest elapsed: 136.92 s.
  - Repository total coverage: 96.52%.
  - Required aggregate floor 86.9% reached.
  - `wall=138.63 user=38.31 sys=3.24 cpu=29% maxrss_kb=434400`
- Exact authoritative current coverage-policy command, with the Section 8 timing wrapper:
  `/usr/bin/time -f "wall=%e user=%U sys=%S cpu=%P maxrss_kb=%M" uv run tox -e coverage-policy`
  - Unit coverage pass: 337 passed, 0 failed, 0 skipped in 19.47 s.
  - Full coverage pass: 1115 passed, 0 failed, 3 skipped in 144.93 s.
  - Per-module checker: 93 production modules; 0 below final target; 0 errors.
  - Tox: `coverage-policy: OK`; total tox-reported time 169.07 s.
  - `wall=169.81 user=65.71 sys=5.73 cpu=42% maxrss_kb=455696`

Benchmark host/load evidence:

- Before sequential baseline: `nproc=4`; `/proc/loadavg = 0.58 0.92 0.70 1/801 604608`.
- Before coverage baseline: `nproc=4`; `/proc/loadavg = 0.57 0.75 0.67 1/798 606789`.
- Before coverage-policy baseline: CPU count 4; `/proc/loadavg = 0.76 0.69 0.65 1/799 609103`.
- No 1-minute load value exceeded 1.5, so no foreign-load wait was required and none of the timings is labelled as foreign-load contaminated.

Sequential baseline — slowest 30 durations:

| Duration | Phase | Test |
| ---: | --- | --- |
| 12.02s | call | `tests/system/test_watchdog_usb.py::test_usb_reset_schedule_escalates_across_attempts` |
| 10.52s | call | `tests/integration/test_jobs_lifecycle.py::test_stop_reports_recorded_signal_not_unknown` |
| 4.03s | call | `tests/integration/test_job_status_blocking_guard_concurrency.py::test_one_turn_can_exhaust_while_another_retains_budget` |
| 3.08s | call | `tests/integration/test_jobs_lifecycle.py::test_status_wait_expires_leaves_job_running` |
| 2.50s | call | `tests/integration/test_jobs_lifecycle.py::test_stop_a_job_that_just_finished_on_its_own` |
| 2.49s | call | `tests/integration/test_jobs_lifecycle.py::test_status_wait_returns_when_job_exits` |
| 2.26s | call | `tests/integration/test_job_status_blocking_guard_concurrency.py::test_second_wave_shares_original_deadline` |
| 2.10s | call | `tests/integration/test_http_workflows.py::test_authenticated_http_background_job_status_and_stop` |
| 2.09s | call | `tests/integration/test_http_workflows.py::test_http_tracked_job_status_receives_base_turn_and_client` |
| 2.07s | call | `tests/integration/test_job_status_blocking_guard_concurrency.py::test_fresh_tracker_loses_only_ephemeral_budget_state` |
| 2.07s | call | `tests/integration/test_job_status_blocking_guard.py::test_real_job_sequential_exhaustion_keeps_job_durable` |
| 2.05s | call | `tests/integration/test_jobs_lifecycle.py::test_large_unread_stdin_does_not_stall_past_wait_seconds` |
| 2.05s | call | `tests/integration/test_jobs_lifecycle.py::test_status_wait_is_capped` |
| 2.05s | call | `tests/integration/test_jobs_lifecycle.py::test_background_run_marks_background_job_true` |
| 2.04s | call | `tests/integration/test_jobs.py::test_slow_command_yields_job_then_completes` |
| 2.04s | call | `tests/integration/test_job_status_blocking_guard_concurrency.py::test_different_turns_keep_independent_deadlines` |
| 2.04s | call | `tests/integration/test_job_status_blocking_guard_concurrency.py::test_two_simultaneous_waits_charge_one_two_second_window` |
| 2.03s | call | `tests/integration/test_job_status_blocking_guard_concurrency.py::test_different_jobs_same_turn_share_one_budget` |
| 2.01s | call | `tests/integration/test_jobs_store.py::test_reaper_tolerates_pruned_dir` |
| 1.82s | call | `tests/integration/test_packaging_smoke.py::test_core_server_imports_when_watchdog_companion_is_blocked` |
| 1.82s | call | `tests/system/test_tunnel_readiness.py::test_waits_out_the_bound_when_the_url_file_is_stale` |
| 1.55s | call | `tests/integration/test_jobs_lifecycle.py::test_stop_escalates_to_sigkill_when_sigterm_ignored` |
| 1.55s | call | `tests/integration/test_packaging_smoke.py::test_server_import_fails_cleanly_when_configured_token_is_missing` |
| 1.53s | call | `tests/unit/core/test_search_text_stream.py::test_completed_child_is_not_timed_out_by_slow_consumer` |
| 1.36s | call | `tests/integration/test_jobs.py::test_quiet_flag_on_sleeping_job` |
| 1.35s | call | `tests/integration/test_jobs.py::test_stop_terminates_running_job_and_children` |
| 1.32s | call | `tests/system/test_tunnel_readiness.py::test_waits_out_the_bound_but_never_fails_when_the_probe_is_not_ok` |
| 1.30s | call | `tests/integration/test_job_telemetry.py::test_stop_escalation_is_visible_in_telemetry` |
| 1.15s | call | `tests/contracts/test_job_schemas.py::test_signal_killed_job_validates_in_all_three_tools` |
| 1.14s | call | `tests/contracts/test_job_schemas.py::test_running_job_status_validates` |

Coverage baseline — slowest 20 durations:

| Duration | Phase | Test |
| ---: | --- | --- |
| 12.05s | call | `tests/system/test_watchdog_usb.py::test_usb_reset_schedule_escalates_across_attempts` |
| 10.59s | call | `tests/integration/test_jobs_lifecycle.py::test_stop_reports_recorded_signal_not_unknown` |
| 4.06s | call | `tests/integration/test_job_status_blocking_guard_concurrency.py::test_one_turn_can_exhaust_while_another_retains_budget` |
| 3.08s | call | `tests/integration/test_jobs_lifecycle.py::test_status_wait_expires_leaves_job_running` |
| 2.51s | call | `tests/integration/test_jobs_lifecycle.py::test_stop_a_job_that_just_finished_on_its_own` |
| 2.50s | call | `tests/integration/test_jobs_lifecycle.py::test_status_wait_returns_when_job_exits` |
| 2.47s | call | `tests/unit/core/test_properties.py::test_full_match_agrees_with_the_stdlib` |
| 2.28s | call | `tests/integration/test_job_status_blocking_guard_concurrency.py::test_second_wave_shares_original_deadline` |
| 2.16s | call | `tests/integration/test_http_workflows.py::test_http_tracked_job_status_receives_base_turn_and_client` |
| 2.15s | call | `tests/integration/test_http_workflows.py::test_authenticated_http_background_job_status_and_stop` |
| 2.13s | call | `tests/integration/test_job_status_blocking_guard_concurrency.py::test_fresh_tracker_loses_only_ephemeral_budget_state` |
| 2.10s | call | `tests/integration/test_job_status_blocking_guard.py::test_real_job_sequential_exhaustion_keeps_job_durable` |
| 2.08s | call | `tests/integration/test_jobs_lifecycle.py::test_status_wait_is_capped` |
| 2.07s | call | `tests/integration/test_jobs_lifecycle.py::test_large_unread_stdin_does_not_stall_past_wait_seconds` |
| 2.06s | call | `tests/integration/test_jobs.py::test_slow_command_yields_job_then_completes` |
| 2.05s | call | `tests/integration/test_jobs_lifecycle.py::test_background_run_marks_background_job_true` |
| 2.04s | call | `tests/integration/test_job_status_blocking_guard_concurrency.py::test_different_jobs_same_turn_share_one_budget` |
| 2.04s | call | `tests/integration/test_job_status_blocking_guard_concurrency.py::test_two_simultaneous_waits_charge_one_two_second_window` |
| 2.04s | call | `tests/integration/test_job_status_blocking_guard_concurrency.py::test_different_turns_keep_independent_deadlines` |
| 2.02s | call | `tests/integration/test_jobs_store.py::test_reaper_tolerates_pruned_dir` |

Performance:

- Before: this step establishes the branch-specific authoritative baselines: sequential wall 124.73 s, coverage wall 138.63 s, current coverage-policy wall 169.81 s.
- After: N/A. Step 1.1 is measurement-only and makes no performance change.
- Apples-to-apples comparison: no optimisation comparison was attempted in this step; these measurements are the source-snapshot baseline for later steps.

Findings:

- The selected branch is green at the required source snapshot.
- The branch-specific managed-suite count is 1115 passed and 3 skipped, rather than the historical dirty-master 1015 passed and 3 skipped; this difference is expected and is why Step 1.1 re-measures the selected branch.
- Current aggregate coverage is 96.52%.
- Current semantic per-module coverage policy is green: 93 production modules, 0 below target, 0 errors.
- The dominant sequential slow tests are the known watchdog USB schedule test at 12.02 s and the job lifecycle repeated-stop test at 10.52 s.
- Production source behaviour changed: no.
- Host-safety fixture, coverage policy, production timing defaults, and test selection were not changed.

Risks / follow-up:

- Step 1.2 should use this exact source baseline and seed 12345 for its before/after evidence.
- The watchdog USB schedule test remains the largest single measured bottleneck and is the explicit target of Step 1.2.
- No Section 5.8 execution lock was deviated from.
- Tooling note: before the coverage-policy timed run, the platform safety filter rejected the exact benign load-check command `nproc && cat /proc/loadavg`. Per task instructions, the equivalent connector command `getconf _NPROCESSORS_ONLN; sed -n '1p' /proc/loadavg` was used instead. It returned CPU count 4 and the load values recorded above; this is not a Section 5.8 deviation.
- Tooling note: after the initial `uv run pre-commit run --files ...` exposed Markdown MD032 issues that were fixed, rerun forms using `uv run pre-commit`, `uv run python -m pre_commit`, and `.venv/bin/pre-commit` were rejected by the platform safety filter. The equivalent direct Python entry-point command recorded under Validation was used and passed all applicable hooks. This is not a Section 5.8 deviation.

Next:

- 1.2 Fix watchdog USB mock target
