# Phase-3 policy replay

- Corpus SHA-256: 4dd1e387c42d6fccd37d60795b00192144f3b4d93c57d9eb54ab527a72e8e94d
- Candidate shortlist: benchmarks/chat-mode-scheduling-v2/phase3-candidate-shortlist.json
- Candidate shortlist SHA-256: 51db08d70ad8ebfcc46de9e53c661b517b9f3ed41b10579d49057aa395f8d11d
- Verdict: NO_LIVE_CANDIDATE
- Production budget declared: false

## Candidate selection

- Live candidates: none
- Preferred live candidate: none

## Historical H10 comparator

- Path: benchmarks/chat-mode-scheduling-v2/phase3-replay-h10.json
- SHA-256: b769fb75cd4159bf2c12fd92e33c0df62b7dfee775dfb8fb2c5ea6cb5110621c
- Policy: historical-one-shot
- Budget: 10.0 s

The H10 result is historical-comparator evidence only and is not eligible for the live candidate shortlist.

## Evidence limitations and history

- Open evidence limitations from the frozen shortlist: none.
- Replay corpus revision 1 SHA-256
  `c2c2809abde13c7b697e3a8c3e91a547fe68bbd83fdbd816c611b3f0e94808de`
  (report SHA-256
  `b45934afec305a6575fa67e70fbc19407b7e0cfaf0fbab756b53d9571cd13888`)
  is superseded historical diagnostic evidence after the revision-1
  operational-journal audit exposed an extractor/window-count defect.
- Revision-1 operational-journal audit `p3-audit-operational-journal` FAILED at
  commit `5518a09b30fd21356f7659f63f1318b39d769431`; its shard SHA-256 was
  `f1124faced67d51e9ea30311f9dea25e17bd2f82d2c2e0a3cdbb4842de080bbe`.
  The frozen source had 4,073 token-filtered timing lines while the extractor
  compared 4,045 parsed records, incorrectly marking the shard unavailable.
- The defect was fixed in `c7b0b8bf1c308812d3b391c556b8a302d5b8c125`;
  corpus revision 2 SHA-256
  `4dd1e387c42d6fccd37d60795b00192144f3b4d93c57d9eb54ab527a72e8e94d`
  was re-extracted and independently audited PASS and is the only corpus used
  for Phase-3 acceptance.
