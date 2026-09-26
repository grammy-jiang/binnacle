# Phase 4 4C reliability/provenance evidence review

This review deterministically aggregates the six frozen R1-R11 confirmatory partitions. It does not issue the Phase-4 overall verdict.

## Reliability summary

- Selected C same-prompt completion: **53/53 (100%)**; A is 51/53 (96.2264%), for C-A **+3.773585 pp**.
- Selected C premature handoffs: **0/53**.
- Selected C interruptions: **0/53**; A is 0/53; C-A **+0.000000 pp**.
- Selected C manual continuations: **0** across 53 rows; median and p90 are both 0.
- Continuation-prone reduction: A=0, C=0; the frozen analyzer yields null/undefined because A has no denominator. The >=80% reduction gate is not converted to a pass.

## Partition review

| Partition | A same-prompt | B same-prompt | C same-prompt | Interruptions A/B/C | Premature A/B/C | Routing misses A/B/C |
| --- | ---: | ---: | ---: | --- | --- | --- |
| R1-R2 | 10/10 | 10/10 | 10/10 | 0/0/0 | 0/0/0 | 0/10/0/10/0/10 |
| R3-R4 | 8/10 | 8/10 | 10/10 | 0/0/0 | 0/0/0 | 0/10/0/10/0/10 |
| R5-R6 | 10/10 | 10/10 | 10/10 | 0/0/0 | 0/0/0 | 0/10/0/10/0/10 |
| R7 | 3/3 | 2/3 | 3/3 | 0/1/0 | 0/0/0 | 0/3/0/3/0/3 |
| R8-R9 | 10/10 | 10/10 | 10/10 | 0/0/0 | 0/0/0 | 1/11/0/10/0/10 |
| R10-R11 | 10/10 | 10/10 | 10/10 | 0/0/0 | 0/0/0 | 0/10/0/10/0/10 |

## Routing integrity

- A: **1/54 (1.8519%)**; pre-submit failures 3.
- B: **0/53 (0.0000%)**; pre-submit failures 0.
- C: **0/53 (0.0000%)**; pre-submit failures 0.

No arm exceeds the P4-A2 >10% routing-miss evidence-integrity threshold. R9-r03-A had one non-owning production routing miss with eight production calls; attempt 2 is the correctly routed owner.

## Provenance

All **159/159** canonical R1-R11 performance owners passed archive SHA, run/scenario/arm/endpoint identity, frozen source HEAD, verified-unmutated instruction identity, and evidence-integrity checks. Frozen experiment source HEAD: 06bc1649c4bad9449470366da971649bb7620020.

Submitted-owner rows with explicit provenance classification:

- R2-r04-A (A): trial status failed, submission completed, provenance other_submitted_error, error HarnessError.
- R7-r02-B (B): trial status failed, submission failed_after_submission, provenance mcp_completed_browser_timeout, error TimeoutExpired.

R7-r02-B is the sole interruption: endpoint evidence is correctly routed and clean, MCP work completed, and browser/send observation timed out. R2-r04-A is a same-prompt-complete non-interruption retained under the first-submitted rule; its other_submitted_error attribution is the unrelated production Git-status drift frozen by 4.9.1.

## D9 timing provenance

**86** trials were recomputed from raw conversation final-assistant timestamps: 7 during checkpointing and 79 during post-run deferred cleanup. **4** trials remain poll-observed. No wall-time aggregate is computed in this focus.

### Recomputed trials

- R1-r01-C (R1-R2): 68.848 s -> 18.055 s, conversation_final_assistant_timestamp.
- R1-r03-A (R1-R2): 70.709 s -> 24.385 s, conversation_final_assistant_timestamp.
- R1-r03-B (R1-R2): 75.802 s -> 17.95 s, conversation_final_assistant_timestamp.
- R1-r05-A (R1-R2): 51.664 s -> 18.74 s, conversation_final_assistant_timestamp.
- R1-r05-B (R1-R2): 63.412 s -> 19.238 s, conversation_final_assistant_timestamp.
- R1-r05-C (R1-R2): 70.931 s -> 19.571 s, conversation_final_assistant_timestamp.
- R2-r02-B (R1-R2): 25.373 s -> 15.862 s, conversation_final_assistant_timestamp.
- R2-r02-C (R1-R2): 72.551 s -> 17.613 s, conversation_final_assistant_timestamp.
- R2-r03-A (R1-R2): 50.09 s -> 20.48 s, conversation_final_assistant_timestamp.
- R2-r04-A (R1-R2): 54.22 s -> 16.722 s, conversation_final_assistant_timestamp.
- R10-r01-A (R10-R11): 130.823 s -> 102.436 s, conversation_final_assistant_timestamp.
- R10-r01-B (R10-R11): 131.224 s -> 106.72 s, conversation_final_assistant_timestamp.
- R10-r01-C (R10-R11): 128.197 s -> 101.059 s, conversation_final_assistant_timestamp.
- R10-r02-A (R10-R11): 110.064 s -> 104.888 s, conversation_final_assistant_timestamp.
- R10-r02-B (R10-R11): 115.15 s -> 105.644 s, conversation_final_assistant_timestamp.
- R10-r02-C (R10-R11): 116.765 s -> 104.096 s, conversation_final_assistant_timestamp.
- R10-r04-A (R10-R11): 172.378 s -> 115.091 s, conversation_final_assistant_timestamp.
- R10-r04-B (R10-R11): 104.774 s -> 103.143 s, conversation_final_assistant_timestamp.
- R10-r04-C (R10-R11): 156.978 s -> 104.43 s, conversation_final_assistant_timestamp.
- R11-r01-B (R10-R11): 51.781 s -> 31.483 s, conversation_final_assistant_timestamp.
- R11-r05-A (R10-R11): 70.239 s -> 30.393 s, conversation_final_assistant_timestamp.
- R11-r05-B (R10-R11): 73.622 s -> 29.061 s, conversation_final_assistant_timestamp.
- R11-r05-C (R10-R11): 70.806 s -> 27.828 s, conversation_final_assistant_timestamp.
- R3-r02-A (R3-R4): 50.526 s -> 43.92 s, conversation_final_assistant_timestamp.
- R3-r02-B (R3-R4): 52.603 s -> 45.124 s, conversation_final_assistant_timestamp.
- R3-r03-B (R3-R4): 63.789 s -> 44.85 s, conversation_final_assistant_timestamp.
- R3-r03-C (R3-R4): 52.166 s -> 46.12 s, conversation_final_assistant_timestamp.
- R3-r04-B (R3-R4): 51.6 s -> 45.651 s, conversation_final_assistant_timestamp.
- R3-r05-A (R3-R4): 75.465 s -> 44.15 s, conversation_final_assistant_timestamp.
- R4-r01-A (R3-R4): 124.615 s -> 106.955 s, conversation_final_assistant_timestamp.
- R4-r01-B (R3-R4): 150.05 s -> 109.289 s, conversation_final_assistant_timestamp.
- R4-r01-C (R3-R4): 339.255 s -> 110.934 s, conversation_final_assistant_timestamp.
- R4-r02-A (R3-R4): 129.725 s -> 108.481 s, conversation_final_assistant_timestamp.
- R4-r02-B (R3-R4): 105.805 s -> 104.523 s, conversation_final_assistant_timestamp.
- R4-r02-C (R3-R4): 113.551 s -> 106.782 s, conversation_final_assistant_timestamp.
- R4-r03-B (R3-R4): 127.739 s -> 103.214 s, conversation_final_assistant_timestamp.
- R4-r03-C (R3-R4): 161.673 s -> 108.355 s, conversation_final_assistant_timestamp.
- R4-r04-A (R3-R4): 174.695 s -> 104.19 s, conversation_final_assistant_timestamp.
- R4-r04-C (R3-R4): 127.515 s -> 106.725 s, conversation_final_assistant_timestamp.
- R4-r05-A (R3-R4): 122.636 s -> 108.637 s, conversation_final_assistant_timestamp.
- R4-r05-B (R3-R4): 130.743 s -> 111.233 s, conversation_final_assistant_timestamp.
- R4-r05-C (R3-R4): 126.057 s -> 106.218 s, conversation_final_assistant_timestamp.
- R5-r01-B (R5-R6): 51.311 s -> 39.389 s, conversation_final_assistant_timestamp.
- R5-r01-C (R5-R6): 39.867 s -> 35.378 s, conversation_final_assistant_timestamp.
- R5-r02-A (R5-R6): 187.849 s -> 48.802 s, conversation_final_assistant_timestamp.
- R5-r02-B (R5-R6): 70.774 s -> 43.491 s, conversation_final_assistant_timestamp.
- R5-r02-C (R5-R6): 73.489 s -> 38.046 s, conversation_final_assistant_timestamp.
- R5-r04-A (R5-R6): 63.92 s -> 38.776 s, conversation_final_assistant_timestamp.
- R5-r04-C (R5-R6): 51.24 s -> 37.001 s, conversation_final_assistant_timestamp.
- R5-r05-A (R5-R6): 50.147 s -> 39.654 s, conversation_final_assistant_timestamp.
- R6-r01-A (R5-R6): 172.771 s -> 103.87 s, conversation_final_assistant_timestamp.
- R6-r02-A (R5-R6): 129.431 s -> 103.016 s, conversation_final_assistant_timestamp.
- R6-r02-B (R5-R6): 117.778 s -> 106.392 s, conversation_final_assistant_timestamp.
- R6-r03-A (R5-R6): 155.591 s -> 102.347 s, conversation_final_assistant_timestamp.
- R6-r03-C (R5-R6): 136.337 s -> 101.081 s, conversation_final_assistant_timestamp.
- R6-r04-B (R5-R6): 173.411 s -> 101.32 s, conversation_final_assistant_timestamp.
- R6-r04-C (R5-R6): 130.239 s -> 105.69 s, conversation_final_assistant_timestamp.
- R6-r05-A (R5-R6): 108.206 s -> 104.7 s, conversation_final_assistant_timestamp.
- R6-r05-B (R5-R6): 114.779 s -> 104.824 s, conversation_final_assistant_timestamp.
- R7-r01-A (R7): 168.054 s -> 157.185 s, conversation_final_assistant_timestamp.
- R7-r01-B (R7): 186.229 s -> 157.27 s, conversation_final_assistant_timestamp.
- R7-r01-C (R7): 158.269 s -> 154.656 s, conversation_final_assistant_timestamp.
- R7-r03-C (R7): 160.772 s -> 157.1 s, conversation_final_assistant_timestamp.
- R8-r01-A (R8-R9): 53.014 s -> 25.173 s, conversation_final_assistant_timestamp.
- R8-r01-B (R8-R9): 69.297 s -> 27.84 s, conversation_final_assistant_timestamp.
- R8-r02-B (R8-R9): 61.271 s -> 34.528 s, conversation_final_assistant_timestamp.
- R8-r02-C (R8-R9): 54.012 s -> 46.598 s, conversation_final_assistant_timestamp.
- R8-r03-C (R8-R9): 190.069 s -> 33.195 s, conversation_final_assistant_timestamp.
- R8-r04-A (R8-R9): 65.032 s -> 31.519 s, conversation_final_assistant_timestamp.
- R8-r04-B (R8-R9): 68.53 s -> 28.584 s, conversation_final_assistant_timestamp.
- R8-r04-C (R8-R9): 65.486 s -> 25.237 s, conversation_final_assistant_timestamp.
- R8-r05-A (R8-R9): 61.632 s -> 26.418 s, conversation_final_assistant_timestamp.
- R8-r05-B (R8-R9): 51.18 s -> 24.782 s, conversation_final_assistant_timestamp.
- R8-r05-C (R8-R9): 64.08 s -> 28.271 s, conversation_final_assistant_timestamp.
- R9-r01-A (R8-R9): 63.91 s -> 52.51 s, conversation_final_assistant_timestamp.
- R9-r01-B (R8-R9): 175.869 s -> 63.281 s, conversation_final_assistant_timestamp.
- R9-r01-C (R8-R9): 62.845 s -> 53.674 s, conversation_final_assistant_timestamp.
- R9-r02-A (R8-R9): 51.972 s -> 43.762 s, conversation_final_assistant_timestamp.
- R9-r02-C (R8-R9): 64.861 s -> 41.332 s, conversation_final_assistant_timestamp.
- R9-r03-B (R8-R9): 122.803 s -> 70.673 s, conversation_final_assistant_timestamp.
- R9-r03-C (R8-R9): 70.738 s -> 59.37 s, conversation_final_assistant_timestamp.
- R9-r04-A (R8-R9): 124.946 s -> 73.475 s, conversation_final_assistant_timestamp.
- R9-r04-B (R8-R9): 101.649 s -> 68.163 s, conversation_final_assistant_timestamp.
- R9-r04-C (R8-R9): 75.257 s -> 62.502 s, conversation_final_assistant_timestamp.
- R9-r05-A (R8-R9): 51.208 s -> 41.18 s, conversation_final_assistant_timestamp.
- R9-r05-C (R8-R9): 62.079 s -> 54.978 s, conversation_final_assistant_timestamp.

### Still poll-observed

- R5-r03-C (R5-R6): 40.268 s; checkpoint reason read_chat_timeout_12s; latest cleanup error: CalledProcessError: Command '['/usr/bin/python3', '/home/grammy-jiang/Projects/binnacle-chat-scheduling-phase4-review-reliability-provenance/.claude/skills/chatgpt-mcp-dev/scripts/chatgpt-chats', '--browser', 'chrome', '--id', '6ab691e5-fe58-83ec-a8cd-69d1f0063531', '--delete']' returned non-zero exit status 1..
- R6-r01-C (R5-R6): 104.552 s; checkpoint reason read_chat_timeout_12s; latest cleanup error: CalledProcessError: Command '['/usr/bin/python3', '/home/grammy-jiang/Projects/binnacle-chat-scheduling-phase4-review-reliability-provenance/.claude/skills/chatgpt-mcp-dev/scripts/chatgpt-chats', '--browser', 'chrome', '--id', '6ab692e0-e7c4-83ec-9e3f-a1f69dede754', '--delete']' returned non-zero exit status 1..
- R6-r02-C (R5-R6): 108.399 s; checkpoint reason read_chat_timeout_12s; latest cleanup error: CalledProcessError: Command '['/usr/bin/python3', '/home/grammy-jiang/Projects/binnacle-chat-scheduling-phase4-review-reliability-provenance/.claude/skills/chatgpt-mcp-dev/scripts/chatgpt-chats', '--browser', 'chrome', '--id', '6ab6940b-36a8-83ec-ac04-396785988af1', '--delete']' returned non-zero exit status 1..
- R7-r02-C (R7): 155.16 s; checkpoint reason read_chat_timeout_30s; latest cleanup error: CalledProcessError: Command '['/usr/bin/python3', '/home/grammy-jiang/Projects/binnacle-chat-scheduling-phase4-review-reliability-provenance/.claude/skills/chatgpt-mcp-dev/scripts/chatgpt-chats', '--browser', 'chrome', '--id', '6ab6992c-8b00-83ec-8a12-1343f148d63e', '--delete']' returned non-zero exit status 1..

## Focus gate records

- premature_handoff_zero: **PASS**.
- same_prompt_completion_ge_95_percent: **PASS**.
- median_manual_continuation_zero: **PASS**.
- p90_manual_continuation_zero: **PASS**.
- continuation_reduction_ge_80_percent: **FAIL**.
- interruption_rate_le_a_plus_2pp: **PASS**.

The continuation-reduction failure is mechanical: both A and C have zero required continuations in the frozen continuation-prone cohort, so the analyzer-defined percentage is null rather than >=80%.

## Deterministic inputs

- R1-R2 scratch SHA-256 180e6940e2d6e7e910c7453953baeae73d365eb3dd2ba025c4c17d6d082eacd0; checkpoint SHA-256 bf8bdc772fe586cef3bd893df44144f126d891357d81b9002e921798a4da292b; evidence-tree SHA-256 b36db72b69392d863401faaa452992077ab3ae45661b8dd3bbb1ef990e0030f1.
- R3-R4 scratch SHA-256 350842b5527d09e8c8f1b1cb4be39466730ce199e82dd10ee09c23856cc6a466; checkpoint SHA-256 6f1ac078cab68ecbbf2435e688e040ca0453992e411eb427624595ed43f17bdd; evidence-tree SHA-256 3c73d3025bf97e5f477e1a30e11f56ad8bba81a1180293bac0e937ef1fd11ef5.
- R5-R6 scratch SHA-256 c5e6c10f8356612cfa8f2ba49a0b31b060277f0898f1e6bede025ec7e91452c9; checkpoint SHA-256 0938d4b6abc7cd5258591f46c142a28dde963e32dfe30ffc8ead1f4a78fcc589; evidence-tree SHA-256 50c4524bf5a9b14df36d6973333cf51882fcade84daac3e3088476b75c7c3a3a.
- R7 scratch SHA-256 f59de892697916e8d4cc063590403c1c6117d6fab691e16122a2037e022e13d8; checkpoint SHA-256 344e2b5f372e46dc80dab7df0166a86e58cf5624b358664d2d48bd3b8ffec63a; evidence-tree SHA-256 e64ba86062d91863653bfed02946b9e0fb95ed0285009af8c9bdfb4d82a5ecf6.
- R8-R9 scratch SHA-256 6f40af60b5982c35c5de1d91856702c2c05b5f0c57f7cfe0577a140072f09656; checkpoint SHA-256 f58ec042664049bb0df964c4a035f96d6378f82f45fe820e7af41718e44453c8; evidence-tree SHA-256 e86cf96dd2b58c9402d9b7d4adf0440189c369da79dddd000ac6528108c844f7.
- R10-R11 scratch SHA-256 4805777cc4d4cc65da92deae8dd4606105744a6b3187e37cd06dab6ad8999880; checkpoint SHA-256 d7dbe437d1ca39c090bad760eecee647115a059f782aef39b5fb086414b3de14; evidence-tree SHA-256 4d626494f71b0465e797adf13ccfeeba7eed5a82ff74d72d116961abb006e6d2.

The canonical 4.11 fan-in remains orchestrator-owned.

## Analyzer cross-check blocker

The required frozen analyzer cross-check does not agree with the six frozen 4.9 checkpoint owners. The review is therefore blocked rather than normalized.

- Frozen checkpoint aggregate for selected C: 53/53 same-prompt completion, 0/53 premature handoffs, 0/53 interruptions.
- Frozen analyzer over the full historical runs root: 45/53 same-prompt completion, 3/53 premature handoffs, 0/53 interruptions; only 48/53 C performance slots are scored.
- The analyzer also reports slot-integrity issues, including canonical slots assigned rows with missing metrics/evidence errors plus many unscheduled historical submissions.
- Source cause in the frozen analyzer: submitted trials without explicit schedule slot/repeat identity enter loose assignment and are paired by earliest (scenario, arm) order. This selects historical runs instead of the six checkpoint-frozen owners.
- Running the required gate command with this review artifact raises ValueError: review artifacts disagree with canonical metrics on premature_handoff_zero. The disagreement is preserved as the blocking validation result.
