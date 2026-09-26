# Phase 4 4C reliability/provenance evidence review

This attempt-a2 review deterministically aggregates the six frozen R1-R11 confirmatory partitions and the P4-A6 timing addenda. It does not issue the Phase-4 overall verdict.

## A1 blocker resolution

- frozen_analyzer_vs_frozen_checkpoint_owner_disagreement: **RESOLVED** by P4-A6 D10a/D10b/D10c.
- The repaired analyzer now reports **160/160 submitted** and **160/160 scorable** main slots with **0 slot-integrity issues**.
- The repaired analyzer agrees with the frozen review on all six reliability/UX gate computations; the gate command exits 0.

## Reliability summary

- Selected C same-prompt completion: **53/53 (100%)**; A is 51/53 (96.2264%), for C-A **+3.773585 pp**.
- Selected C premature handoffs: **0/53**.
- Selected C interruptions: **0/53**; A is 0/53; C-A **+0.000000 pp**.
- Selected C manual continuations: **0** across 53 rows; median and p90 are both 0.
- Continuation-prone reduction: A=0, C=0; the analyzer yields null/undefined because A has no denominator. The >=80% reduction gate is not converted to a pass.

## Partition review

| Partition | A same-prompt | B same-prompt | C same-prompt | Interruptions A/B/C | Premature A/B/C | Routing misses A/B/C | P4-A6 timing rows |
| --- | ---: | ---: | ---: | --- | --- | --- | ---: |
| R1-R2 | 10/10 | 10/10 | 10/10 | 0/0/0 | 0/0/0 | 0/10/0/10/0/10 | 10 |
| R3-R4 | 8/10 | 8/10 | 10/10 | 0/0/0 | 0/0/0 | 0/10/0/10/0/10 | 19 |
| R5-R6 | 10/10 | 10/10 | 10/10 | 0/0/0 | 0/0/0 | 0/10/0/10/0/10 | 12 |
| R7 | 3/3 | 2/3 | 3/3 | 0/1/0 | 0/0/0 | 0/3/0/3/0/3 | 2 |
| R8-R9 | 10/10 | 10/10 | 10/10 | 0/0/0 | 0/0/0 | 1/11/0/10/0/10 | 23 |
| R10-R11 | 10/10 | 10/10 | 10/10 | 0/0/0 | 0/0/0 | 0/10/0/10/0/10 | 13 |

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

## P4-A6 analysis repair verification

- D10a population: **RESOLVED**. Canonical population is 160/160 submitted and scorable with zero issues; historical directory scans no longer choose owners.
- D10b status: **RESOLVED**. R7-r02-B with submission_status=failed_after_submission remains the canonical submitted owner.
- D10c timing: **RESOLVED**. All **79** post-checkpoint recovered timing rows have regenerated metrics.json and trace.json; current hashes match the six timing addenda and the pre-P4-A6 backups match their recorded old hashes.

## D9/P4-A6 timing provenance

**86** trials were recomputed from raw conversation final-assistant timestamps: 7 during checkpointing and 79 during post-run deferred cleanup. P4-A6 regenerated metrics/trace for all **79** post-checkpoint rows. Current timing sources are **155 conversation timestamps** and **4 poll-observed** rows. No wall-time aggregate is computed in this focus.

### Recomputed trials

- R1-r01-C (R1-R2, run r1-20260926T232128-6390f9871b): 68.848 s -> 18.055 s, conversation_final_assistant_timestamp.
- R1-r03-A (R1-R2, run r1-20260926T203729-8abe9e86ac): 70.709 s -> 24.385 s, conversation_final_assistant_timestamp.
- R1-r03-B (R1-R2, run r1-20260926T203525-6ee550efc2): 75.802 s -> 17.95 s, conversation_final_assistant_timestamp.
- R1-r05-A (R1-R2, run r1-20260926T205656-617f5b0e7c): 51.664 s -> 18.74 s, conversation_final_assistant_timestamp.
- R1-r05-B (R1-R2, run r1-20260926T205837-a6adfedbc7): 63.412 s -> 19.238 s, conversation_final_assistant_timestamp.
- R1-r05-C (R1-R2, run r1-20260926T210029-8045d731db): 70.931 s -> 19.571 s, conversation_final_assistant_timestamp.
- R2-r02-B (R1-R2, run r2-20260926T205130-8876637d74): 25.373 s -> 15.862 s, conversation_final_assistant_timestamp.
- R2-r02-C (R1-R2, run r2-20260926T205244-0ba07f1e5d): 72.551 s -> 17.613 s, conversation_final_assistant_timestamp.
- R2-r03-A (R1-R2, run r2-20260926T221656-22d7f01d6f): 50.09 s -> 20.48 s, conversation_final_assistant_timestamp.
- R2-r04-A (R1-R2, run r2-20260927T003210-7c2132fad3): 54.22 s -> 16.722 s, conversation_final_assistant_timestamp.
- R10-r01-A (R10-R11, run r10-20260926T210827-42f18f9d43): 130.823 s -> 102.436 s, conversation_final_assistant_timestamp.
- R10-r01-B (R10-R11, run r10-20260926T210229-269635dd8d): 131.224 s -> 106.72 s, conversation_final_assistant_timestamp.
- R10-r01-C (R10-R11, run r10-20260926T210529-fcd281e693): 128.197 s -> 101.059 s, conversation_final_assistant_timestamp.
- R10-r02-A (R10-R11, run r10-20260926T220537-4a16a7a653): 110.064 s -> 104.888 s, conversation_final_assistant_timestamp.
- R10-r02-B (R10-R11, run r10-20260926T221136-cc88039020): 115.15 s -> 105.644 s, conversation_final_assistant_timestamp.
- R10-r02-C (R10-R11, run r10-20260926T220841-c79ce8945b): 116.765 s -> 104.096 s, conversation_final_assistant_timestamp.
- R10-r04-A (R10-R11, run r10-20260926T233046-eab06ceb13): 172.378 s -> 115.091 s, conversation_final_assistant_timestamp.
- R10-r04-B (R10-R11, run r10-20260926T232759-d4a5465607): 104.774 s -> 103.143 s, conversation_final_assistant_timestamp.
- R10-r04-C (R10-R11, run r10-20260926T233448-cd6f149f35): 156.978 s -> 104.43 s, conversation_final_assistant_timestamp.
- R11-r01-B (R10-R11, run r11-20260926T222300-e24c838366): 51.781 s -> 31.483 s, conversation_final_assistant_timestamp.
- R11-r05-A (R10-R11, run r11-20260926T211127-0d064f8436): 70.239 s -> 30.393 s, conversation_final_assistant_timestamp.
- R11-r05-B (R10-R11, run r11-20260926T211524-0f5885a101): 73.622 s -> 29.061 s, conversation_final_assistant_timestamp.
- R11-r05-C (R10-R11, run r11-20260926T211327-11e5aba83b): 70.806 s -> 27.828 s, conversation_final_assistant_timestamp.
- R3-r02-A (R3-R4, run r3-20260926T214500-5a03f81a00): 50.526 s -> 43.92 s, conversation_final_assistant_timestamp.
- R3-r02-B (R3-R4, run r3-20260926T214642-5ebcd84104): 52.603 s -> 45.124 s, conversation_final_assistant_timestamp.
- R3-r03-B (R3-R4, run r3-20260926T230442-fe3705276a): 63.789 s -> 44.85 s, conversation_final_assistant_timestamp.
- R3-r03-C (R3-R4, run r3-20260926T230256-0cc9d192de): 52.166 s -> 46.12 s, conversation_final_assistant_timestamp.
- R3-r04-B (R3-R4, run r3-20260926T191952-841fbe993f): 51.6 s -> 45.651 s, conversation_final_assistant_timestamp.
- R3-r05-A (R3-R4, run r3-20260926T195201-fefc5ce1bd): 75.465 s -> 44.15 s, conversation_final_assistant_timestamp.
- R4-r01-A (R3-R4, run r4-20260926T174331-52f9ca9835): 124.615 s -> 106.955 s, conversation_final_assistant_timestamp.
- R4-r01-B (R3-R4, run r4-20260926T173333-32be35d755): 150.05 s -> 109.289 s, conversation_final_assistant_timestamp.
- R4-r01-C (R3-R4, run r4-20260926T173658-4c0f611091): 339.255 s -> 110.934 s, conversation_final_assistant_timestamp.
- R4-r02-A (R3-R4, run r4-20260926T220228-61f5d422e3): 129.725 s -> 108.481 s, conversation_final_assistant_timestamp.
- R4-r02-B (R3-R4, run r4-20260926T215658-b07da72b14): 105.805 s -> 104.523 s, conversation_final_assistant_timestamp.
- R4-r02-C (R3-R4, run r4-20260926T215940-934717f21a): 113.551 s -> 106.782 s, conversation_final_assistant_timestamp.
- R4-r03-B (R3-R4, run r4-20260926T224526-8d9ea11bf6): 127.739 s -> 103.214 s, conversation_final_assistant_timestamp.
- R4-r03-C (R3-R4, run r4-20260926T225056-cb4bc539d3): 161.673 s -> 108.355 s, conversation_final_assistant_timestamp.
- R4-r04-A (R3-R4, run r4-20260926T170143-1203fcbcca): 174.695 s -> 104.19 s, conversation_final_assistant_timestamp.
- R4-r04-C (R3-R4, run r4-20260926T165830-b01ee98fd3): 127.515 s -> 106.725 s, conversation_final_assistant_timestamp.
- R4-r05-A (R3-R4, run r4-20260926T231235-7ff3c866ac): 122.636 s -> 108.637 s, conversation_final_assistant_timestamp.
- R4-r05-B (R3-R4, run r4-20260926T231827-e372a9e8f8): 130.743 s -> 111.233 s, conversation_final_assistant_timestamp.
- R4-r05-C (R3-R4, run r4-20260926T231532-bdefeb0234): 126.057 s -> 106.218 s, conversation_final_assistant_timestamp.
- R5-r01-B (R5-R6, run r5-20260926T190946-e6cc605c99): 51.311 s -> 39.389 s, conversation_final_assistant_timestamp.
- R5-r01-C (R5-R6): 39.867 s -> 35.378 s, conversation_final_assistant_timestamp.
- R5-r02-A (R5-R6): 187.849 s -> 48.802 s, conversation_final_assistant_timestamp.
- R5-r02-B (R5-R6): 70.774 s -> 43.491 s, conversation_final_assistant_timestamp.
- R5-r02-C (R5-R6): 73.489 s -> 38.046 s, conversation_final_assistant_timestamp.
- R5-r04-A (R5-R6, run r5-20260926T231038-7f1c642969): 63.92 s -> 38.776 s, conversation_final_assistant_timestamp.
- R5-r04-C (R5-R6, run r5-20260926T230857-d085096042): 51.24 s -> 37.001 s, conversation_final_assistant_timestamp.
- R5-r05-A (R5-R6, run r5-20260926T193900-f171fb5412): 50.147 s -> 39.654 s, conversation_final_assistant_timestamp.
- R6-r01-A (R5-R6, run r6-20260926T200405-849aff78d2): 172.771 s -> 103.87 s, conversation_final_assistant_timestamp.
- R6-r02-A (R5-R6, run r6-20260926T234127-a2b52ceb93): 129.431 s -> 103.016 s, conversation_final_assistant_timestamp.
- R6-r02-B (R5-R6, run r6-20260926T233833-69d6ae63c0): 117.778 s -> 106.392 s, conversation_final_assistant_timestamp.
- R6-r03-A (R5-R6, run r6-20260926T223603-40ca551ab7): 155.591 s -> 102.347 s, conversation_final_assistant_timestamp.
- R6-r03-C (R5-R6): 136.337 s -> 101.081 s, conversation_final_assistant_timestamp.
- R6-r04-B (R5-R6, run r6-20260926T193256-156a9d2f3e): 173.411 s -> 101.32 s, conversation_final_assistant_timestamp.
- R6-r04-C (R5-R6, run r6-20260926T192727-e12075f8c6): 130.239 s -> 105.69 s, conversation_final_assistant_timestamp.
- R6-r05-A (R5-R6, run r6-20260926T202954-f42c537d09): 108.206 s -> 104.7 s, conversation_final_assistant_timestamp.
- R6-r05-B (R5-R6, run r6-20260926T203231-0bceaf425e): 114.779 s -> 104.824 s, conversation_final_assistant_timestamp.
- R7-r01-A (R7, run r7-20260926T181657-83b81b3556): 168.054 s -> 157.185 s, conversation_final_assistant_timestamp.
- R7-r01-B (R7, run r7-20260926T182033-09141708b5): 186.229 s -> 157.27 s, conversation_final_assistant_timestamp.
- R7-r01-C (R7): 158.269 s -> 154.656 s, conversation_final_assistant_timestamp.
- R7-r03-C (R7): 160.772 s -> 157.1 s, conversation_final_assistant_timestamp.
- R8-r01-A (R8-R9, run r8-20260926T185958-f1a56adbf8): 53.014 s -> 25.173 s, conversation_final_assistant_timestamp.
- R8-r01-B (R8-R9, run r8-20260926T185329-13bfd189f0): 69.297 s -> 27.84 s, conversation_final_assistant_timestamp.
- R8-r02-B (R8-R9, run r8-20260926T175139-e7cc4d893c): 61.271 s -> 34.528 s, conversation_final_assistant_timestamp.
- R8-r02-C (R8-R9, run r8-20260926T174957-87a5d299a2): 54.012 s -> 46.598 s, conversation_final_assistant_timestamp.
- R8-r03-C (R8-R9, run r8-20260926T214825-e33a94540d): 190.069 s -> 33.195 s, conversation_final_assistant_timestamp.
- R8-r04-A (R8-R9, run r8-20260926T224126-3ebfc36216): 65.032 s -> 31.519 s, conversation_final_assistant_timestamp.
- R8-r04-B (R8-R9, run r8-20260926T223928-5398cde99e): 68.53 s -> 28.584 s, conversation_final_assistant_timestamp.
- R8-r04-C (R8-R9, run r8-20260926T224330-e5a3d07fae): 65.486 s -> 25.237 s, conversation_final_assistant_timestamp.
- R8-r05-A (R8-R9, run r8-20260926T213243-6fc24b6480): 61.632 s -> 26.418 s, conversation_final_assistant_timestamp.
- R8-r05-B (R8-R9, run r8-20260926T212856-d9857d7de6): 51.18 s -> 24.782 s, conversation_final_assistant_timestamp.
- R8-r05-C (R8-R9, run r8-20260926T213042-5e27c27b63): 64.08 s -> 28.271 s, conversation_final_assistant_timestamp.
- R9-r01-A (R8-R9, run r9-20260926T214029-bcbe900b68): 63.91 s -> 52.51 s, conversation_final_assistant_timestamp.
- R9-r01-B (R8-R9, run r9-20260926T213639-3066107040): 175.869 s -> 63.281 s, conversation_final_assistant_timestamp.
- R9-r01-C (R8-R9, run r9-20260926T213444-7a34f53da1): 62.845 s -> 53.674 s, conversation_final_assistant_timestamp.
- R9-r02-A (R8-R9, run r9-20260926T192358-44dc6afbc0): 51.972 s -> 43.762 s, conversation_final_assistant_timestamp.
- R9-r02-C (R8-R9, run r9-20260926T192535-b9bb574f29): 64.861 s -> 41.332 s, conversation_final_assistant_timestamp.
- R9-r03-B (R8-R9, run r9-20260926T182633-da25215d9d): 122.803 s -> 70.673 s, conversation_final_assistant_timestamp.
- R9-r03-C (R8-R9, run r9-20260926T182427-ca17fa57f2): 70.738 s -> 59.37 s, conversation_final_assistant_timestamp.
- R9-r04-A (R8-R9, run r9-20260926T171433-61c8f2f318): 124.946 s -> 73.475 s, conversation_final_assistant_timestamp.
- R9-r04-B (R8-R9, run r9-20260926T171156-9e2d3b4f55): 101.649 s -> 68.163 s, conversation_final_assistant_timestamp.
- R9-r04-C (R8-R9, run r9-20260926T171726-80b4d2f934): 75.257 s -> 62.502 s, conversation_final_assistant_timestamp.
- R9-r05-A (R8-R9, run r9-20260926T204735-b4486903fa): 51.208 s -> 41.18 s, conversation_final_assistant_timestamp.
- R9-r05-C (R8-R9, run r9-20260926T204936-bd0aa28852): 62.079 s -> 54.978 s, conversation_final_assistant_timestamp.

### Still poll-observed

- R5-r03-C (R5-R6, run r5-20260926T011904-c834d991d6): 40.268 s; read_chat_timeout_12s.
- R6-r01-C (R5-R6, run r6-20260926T012431-17c772cd31): 104.552 s; read_chat_timeout_12s.
- R6-r02-C (R5-R6, run r6-20260926T012946-4ee162a667): 108.399 s; read_chat_timeout_12s.
- R7-r02-C (R7, run r7-20260926T014904-e32fdb3f45): 155.16 s; read_chat_timeout_30s.

## Focus gate records

- premature_handoff_zero: **PASS**.
- same_prompt_completion_ge_95_percent: **PASS**.
- median_manual_continuation_zero: **PASS**.
- p90_manual_continuation_zero: **PASS**.
- continuation_reduction_ge_80_percent: **FAIL**.
- interruption_rate_le_a_plus_2pp: **PASS**.

The continuation-reduction failure is mechanical: both A and C have zero required continuations in the frozen continuation-prone cohort, so the analyzer-defined percentage is null rather than >=80%.

## Analyzer cross-check

**PASS.** The P4-A6 repaired analyzer agrees with the frozen checkpoint owners and this review. It reports C at 53/53 same-prompt completion, 0 premature handoffs, 0 interruptions, 53/53 scored performance slots, and no slot-integrity issues.

## Deterministic inputs

- R1-R2: scratch SHA-256 5bb36168501d870b25c1cd6e755d3c328b3213c49d5e7d608df57ff0cc8d776b; checkpoint SHA-256 bf8bdc772fe586cef3bd893df44144f126d891357d81b9002e921798a4da292b; timing-addendum SHA-256 042ebd866e134141fad41d37c9fabde017cd4eb084d5ef898664fafb39b1f4a8; evidence-tree SHA-256 b36db72b69392d863401faaa452992077ab3ae45661b8dd3bbb1ef990e0030f1.
- R3-R4: scratch SHA-256 2617864ac96ced4d2cbefa645270bc26b058dd210529b05209b2398bbebfeae7; checkpoint SHA-256 6f1ac078cab68ecbbf2435e688e040ca0453992e411eb427624595ed43f17bdd; timing-addendum SHA-256 a900482a52f997432fd8b75356572c6d452e2349337a171bf60a40e6a130b295; evidence-tree SHA-256 3c73d3025bf97e5f477e1a30e11f56ad8bba81a1180293bac0e937ef1fd11ef5.
- R5-R6: scratch SHA-256 0c1bf62795887cc3ba683375048a6a825b7fd11de4c38e7ccd807a2d35240b88; checkpoint SHA-256 0938d4b6abc7cd5258591f46c142a28dde963e32dfe30ffc8ead1f4a78fcc589; timing-addendum SHA-256 82e12eefca1fe11eb07470548ba50f6fa7140b073a8dcb92162e3e737a35effa; evidence-tree SHA-256 50c4524bf5a9b14df36d6973333cf51882fcade84daac3e3088476b75c7c3a3a.
- R7: scratch SHA-256 1aa892d1dc2bad659e5272b15d67938fee2ef447c3965fbcf34139564e3969e8; checkpoint SHA-256 344e2b5f372e46dc80dab7df0166a86e58cf5624b358664d2d48bd3b8ffec63a; timing-addendum SHA-256 b473d7c4c62982d3cff4e283d9f4f08a564cfac97aa0b410169bbdba0e9792ea; evidence-tree SHA-256 e64ba86062d91863653bfed02946b9e0fb95ed0285009af8c9bdfb4d82a5ecf6.
- R8-R9: scratch SHA-256 8b20894115919684d833ca708ea17cdb964363e7c0abd478317043c89144b8fa; checkpoint SHA-256 f58ec042664049bb0df964c4a035f96d6378f82f45fe820e7af41718e44453c8; timing-addendum SHA-256 30cc571c8131534ce1ae0c1404954a17b8e69446f7ec54ade28e717613af939c; evidence-tree SHA-256 e86cf96dd2b58c9402d9b7d4adf0440189c369da79dddd000ac6528108c844f7.
- R10-R11: scratch SHA-256 bf29391eee640d079799009ce9df2114c1dece78d785e71f1f5ab49ada62938b; checkpoint SHA-256 d7dbe437d1ca39c090bad760eecee647115a059f782aef39b5fb086414b3de14; timing-addendum SHA-256 73cf2c7fb65ae852977566d1938aef24330bf16be5bc433fddb2f59a7a5bb672; evidence-tree SHA-256 4d626494f71b0465e797adf13ccfeeba7eed5a82ff74d72d116961abb006e6d2.

The canonical 4.11 fan-in remains orchestrator-owned.
