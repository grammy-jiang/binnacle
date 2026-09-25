# Chat mode scheduling v2 — Phase 4 baseline snapshot

Captured: `2026-09-25T15:59:43+10:00`

## Frozen source

- Phase-4 source HEAD: `06bc1649c4bad9449470366da971649bb7620020`.
- Direct Phase-3 predecessor HEAD: `3a4dfb1b248e4530fb09013976abb863c8e35eaf`.
- A/B/C/H logical arms and every physical C endpoint must use the frozen Phase-4 source HEAD.

## Baseline Project instructions

- Source Project: `rp-test-sandbox` (`g-p-6aaea9da2bc881918d6f9eb5177cf904`).
- Exact instruction text is stored outside Git at `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/phase4/baseline-instructions.txt` with mode `0600`.
- Baseline instruction SHA-256: `f1c100d0ddb93c29f8f78e5a2d28e297d861ba6e2c7e53712ec886dea06bafa5`.
- Capture used explicit Chrome and removes exactly the one trailing newline added by `chatgpt-project` printing; no Project instruction text is committed here.

## Model and browser identity

- Web model: `gpt-5-6-thinking`.
- Thinking effort: `max` (`Extra High`, power-slider position 4 of 5).
- Browser/profile: Google Chrome `Default`; harness browser default `chrome`.
- Cookie source: `/home/grammy-jiang/.config/google-chrome/Default/Cookies`.
- Browser probe: 27 readable cookies, 0 unreadable; session token expiry `2026-12-24`.
- Harness Playwright profile: throwaway profile seeded from the logged-in Chrome Default cookies.

## Frozen instruction and candidate inputs

- Canonical v2 instruction path: `.claude/skills/chatgpt-mcp-dev/references/project-instructions-chat-scheduling-v2.txt`.
- Canonical v2 instruction SHA-256: `b7df6953a3c64bd245b3d5ff13b6f2667e940d5a154e650fec0b10e6a22cf094`.
- Phase-3 candidate shortlist SHA-256: `072556e60fb55f686d872bce4da004bc272e9162e32459f2dc276657faa0e094`.
- Live candidate shortlist: `C300` only; preferred live candidate `C300`.

The historical `baseline-2026-09-23.json` remains historical evidence only and is not the live Phase-4 A definition.
