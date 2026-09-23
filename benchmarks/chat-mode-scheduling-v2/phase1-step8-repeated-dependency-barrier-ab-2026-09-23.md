# Chat mode scheduling v2 — Phase 1 Step 1.8 repeated dependency barrier A/B

Status: **COMPLETE; PERFORMANCE TARGET MET, RELIABILITY TARGET NOT MET**
Date: 2026-09-23 (Australia/Sydney)

## Scope

R7 stresses two true sequential long dependency barriers in one user prompt:

```text
start 60 s job
-> wait until exited
-> start 75 s job
-> wait until exited
-> DONE
```

Three canonical A/B pairs use the existing first-submitted-slot rule. Pre-submit
failures may retry; a submitted timeout remains canonical.

## Canonical results

| Arm | Correct | Same-prompt | Interruptions | Median wall | Completed median wall | Completed tool calls | Completed job_status calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 3/3 | 2/3 | 1/3 | 210.746 s | 191.269 s | 8 | 6 |
| B | 2/3 | 2/3 | 1/3 | 159.423 s | 158.631 s | 6 | 4 |

B's canonical median wall time is **24.4% lower** than A,
meeting the mixed-long-job >=20% performance target. Completed-only median wall
time is **17.1% lower** for B; this is diagnostic only.

Paired wall times:

```text
pair 1: A 210.746 -> B 159.423 s   B/A 0.756
pair 2: A 250.963 -> B 157.840 s   B/A 0.629 (A submitted timeout)
pair 3: A 171.792 -> B 250.251 s   B/A 1.457 (B submitted timeout)
```

Median paired B/A is **0.756**, a 24.4%
paired-median improvement. B is faster in 2/3 pairs.

## Reliability

Both arms have 2/3 = 66.7% same-prompt completion, below the >=95% target.
The failure modes are materially different:

- A2 was submitted and timed out at 250.963 s after the MCP trace had already
  completed both required jobs; frozen conversation evidence contains `DONE`.
- B3 was submitted and timed out at 250.251 s before useful MCP work reached the
  fixture, so it fails both correctness and same-prompt completion.

Thus v2 does not worsen the observed R7 same-prompt rate versus A in this small
sample, but it does not meet the reliability acceptance gate.

## Long-wait mechanism

Among same-prompt-complete trials, B used a median of 4 `job_status` calls versus
A's 6, with median physical tool calls 6 versus 8. B's completed median MCP-result
token volume is 1208.5 versus A's 1669.0.

This is consistent with the v2 rule to treat a background job id as a Future-like
handle and continue legitimate positive waits at a true dependency barrier rather
than returning control to the user. R7 has no useful independent side work, so
`avoidable_idle_wall_s` remains zero by construction.

## Specification correction

The first replay incorrectly rejected completed R7 traces when an agent changed a
subsequent `job_status` wait from 50 seconds to 10/15/20/30 seconds. R7's prompt
requires semantic waiting until `state=exited`; it does not prescribe an exact
physical wait duration.

`wait_seconds` was therefore removed from the logical identity of `wait_first` and
`wait_second`. `job_id`, dependency ordering, and the `state=exited` completion
condition remain mandatory. All canonical evidence was then replayed; no successful
chat was rerun to improve the result. A regression test now covers varying repeated
wait durations.

## Harness infrastructure correction

During Step 1.8, the harness exposed a deterministic environment bug. The harness
runs under `uv`, so helpers with `#!/usr/bin/env python3` inherited the project venv.
That venv lacks the system `dbus` module needed by `chatgpt_session.py` to read the
Chrome GNOME-keyring cookie key. Direct shell probes worked because they used
`/usr/bin/python3`.

The Project helper and destructive chat cleanup now invoke `/usr/bin/python3`
explicitly. The Playwright `chatgpt-send` path is unchanged. This preserves the same
Pi/Chrome/ChatGPT environment used by prior steps; it changes setup/cleanup only,
not measured chat wall time.

Two canonical successful chats later needed manual post-trial deletion/evidence
recovery after transient cleanup failures. Both conversations were backed up, test
chat tracking is now empty, and no R7 fixture directory remains.

## Evidence-selection integrity

Eight attempts failed before any URL/timing submission evidence and are excluded
under the pre-submit retry rule. One additional A trial (`r7-20260923T204125-117dd3c5ea`)
was mistakenly run after A2 had already submitted and timed out. It completed in
173.193 s but is explicitly excluded: accepting it would violate the frozen
first-submitted-slot rule.

## Host / production safety

The resumed Step 1.8 execution did not capture the separate per-trial temperature
and load wrapper used by earlier steps, so no historical host range is claimed.
Production invariants are clean at completion:

- `binnacle-mcp.service` active;
- production `master` worktree clean;
- `rp-test-sandbox` instructions exactly restored;
- zero tracked test chats;
- zero surviving R7 fixture directories.

## Step 1.8 result

**COMPLETE. PERFORMANCE TARGET MET; RELIABILITY TARGET NOT MET.**

R7 provides the clearest long-barrier performance signal so far: B reduces canonical
median wall time by 24.4% and completed-only median by
17.1%, while both arms still suffer one submitted timeout.
The remaining Phase-1 work is Step 1.9 aggregate analysis / go-no-go.
