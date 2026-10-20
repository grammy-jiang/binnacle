# Optional Development Intelligence / LSP — design index

This design was split on 2026-09-30 because the revalidated monolithic document had grown
too large for efficient AI-agent use.

The authoritative entry point is:

- [`docs/lsp-development-intelligence/README.md`](lsp-development-intelligence/README.md)

Detailed documents:

- [Evidence and decisions](lsp-development-intelligence/evidence-and-decisions.md)
- [Runtime architecture](lsp-development-intelligence/runtime-architecture.md)
- [Providers and safety](lsp-development-intelligence/providers-and-safety.md)
- [Product and MCP surface](lsp-development-intelligence/product-surface.md)
- [Session-sized implementation plan](lsp-development-intelligence/implementation-plan.md)
- [Protocol/lifecycle testing](lsp-development-intelligence/testing-core.md)
- [Safety/compatibility testing](lsp-development-intelligence/testing-safety-contracts.md)
- [Semantic quality, performance and providers](lsp-development-intelligence/testing-performance.md)
- [Public surface, CI and release gates](lsp-development-intelligence/testing-release-gates.md)

Current baseline: `master` `f1493ee`.

The old full content is preserved in Git history; do not append new design sections to this
index file.
