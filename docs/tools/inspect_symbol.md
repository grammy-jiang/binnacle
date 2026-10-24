# inspect_symbol — ChatGPT-facing Python navigation via P4 Pyright

## Operational purpose

The original private P4 proof listens only on port 18765 with a synthetic
workspace. By itself it does not make a ChatGPT tool discoverable, and cannot
collect useful agent development usage. The integrated tool exposes
inspect_symbol on the existing authenticated main Binnacle MCP (port 8000).
Internally it forwards to a separate, authenticated, loopback-only P4 service
on port 18767 granted the host's existing ~/Projects root.

With BINNACLE_LSP_BRIDGE_STATE_DIR unset, production has the unchanged tool
surface. Opting in registers one additional read-only tool; no new file-write
authority, arbitrary endpoint selection, workspace registration or raw provider
process control becomes available to clients.

## Tool input / output

- path: relative to ~/Projects, e.g. myrepo/src/pkg/module.py.
  Never an absolute path, parent traversal, symlink escape or arbitrary root.
- line: positive 1-based line number.
- symbol_text: exact token on the line, or column (1-based codepoint).
- reference_limit: optional bound forwarded to P4 (P4 maximum 100).
- include_hover: optionally request hover, subject to P4 capability.
- Output: P4's bounded structured JSON; definitions and references use paths
  relative to the granted root. A partial result does not certify a complete
  repository index. The underlying service enforces authoritative path scope
  and source freshness, not the bridge.

The client cannot supply the private workspace_id grant handle, token,
port, executable or host endpoint. Only a single host-provisioned P4 grant is
accepted. The credential is read from owner-only (0600) files without following
the final symlink; the private endpoint independently authenticates the request.
The main tool never renders secrets or provider exception text.

## Deployment and recovery

1. Keep the original P4 port 18765 private test service intact.
2. Launch a second P4 service with workspace ~/Projects, state directory
   ~/.local/state/binnacle-lsp-chatgpt and port 18767, and the trusted Pyright
   launcher appropriate to the host.
3. Install the new main Binnacle source release, retaining the existing
   service's auth token, config, root allowlist, job owner and tunnel identity.
4. Set BINNACLE_LSP_BRIDGE_STATE_DIR and BINNACLE_LSP_BRIDGE_PORT=18767 in
   only the main MCP service's environment. Restart the main service.
5. Verify ChatGPT identity openai-mcp(ChatGPT) sees inspect_symbol in tools/list
   and can call it through authenticated port 8000 HTTP.
6. Verify real Python source navigation, scope rejection, service recovery,
   structured logging and unaffected existing tools. If validation fails,
   restore the prior main MCP service configuration and restart it, without
   changing the P4 test service or job manager.

Main middleware records tool_call and tool_result with stable
tool=inspect_symbol, durations, count of definitions/references and semantic
status. Source paths and symbol names are hashed in ordinary logs. The P4
private usage journal independently records status and bounded summary facts.
Existing explicit full-capture policy remains unchanged.

The ChatGPT client may need tool discovery refreshed after deployment.
A local P4 health check by itself does not prove visibility through ChatGPT.
