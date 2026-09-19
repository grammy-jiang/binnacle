# Where resource content actually goes

A capability probe answers "does the client call `resources/read`". It does not
answer the question that decides whether a resource is usable: **once read, does
the content reach the model, and does it stay in the conversation?** That needs a
different measurement, on the client's own transcript.

## The short answer

Resource content **is** sent to the model, and it **does** persist into later
turns. A common misreading is that resources render in the UI without entering
the model's context — that is not what "application-controlled" means. Core MCP
describes resources as data the application "retrieves and provides to models as
context", explicitly including "passing raw data directly to the model". The
control split is about **who initiates** the fetch (application or user, rather
than the model), not about who gets to see the result.

## What Claude Code actually does, measured 2026-08-30

An `@server:uri` mention is a **reference, not an eager expansion**. Content is
fetched only when the model needs it, and it then enters the conversation as a
**tool result** — which is why it behaves like any other tool output and is
replayed with the history.

Three observations, each from a separate run against the conformance probe
(`probe://card`, whose only content is `resource canary: r7c41e90`):

1. **Mention + a question about the content** → the model answered `r7c41e90`.
   The value exists nowhere else, so it could only have come from the resource.
   The probe server logged exactly one `resources/read probe://card`.
2. **Mention + "ignore the attachment, reply ACK"** → the probe server logged
   **no** `resources/read` at all, and that session's transcript contains only
   the literal string `@res-test:probe://card`. Nothing was fetched, so nothing
   could be in context. This is what makes the mention a lazy reference.
3. **Two turns in one session** — turn 1 asked for the canary (forcing the
   fetch), turn 2 asked again *without* re-mentioning the resource and with no
   second `resources/read`. The model answered `r7c41e90` from history.

The stored transcript shows the mechanism plainly:

```
[user]      TOOL RESULT: {"contents":[{"uri":"probe://card",
                          "mimeType":"text/plain",
                          "text":"resource canary: r7c41e90\n"}]}
[assistant] TEXT: r7c41e90     <- turn 1
[assistant] TEXT: r7c41e90     <- turn 2, from history
```

Practical consequence: a large resource, once read, occupies context and is
re-sent every turn for the rest of the session. Budget for that.

## How to measure this for another host

Two sources, neither of which is the model's own account of itself:

1. **The server log** — did `resources/read` happen at all, and when? Use
   `mcp-probe`, or the conformance probe's JSONL.
2. **The client's stored transcript** — how does the content appear, and does it
   recur? For Claude Code the sessions are JSONL under
   `~/.claude/projects/<slugified-cwd>/<session-id>.jsonl`. Drive the session
   with an explicit id so the file is easy to find:

```bash
SID=$(python3 -c "import uuid;print(uuid.uuid4())")
claude -p --session-id "$SID" "@srv:probe://card

What is the canary value? Reply with just the value." --permission-mode bypassPermissions
claude -p --resume "$SID" "Without reading anything again, what was that value? \
Answer with the value or NOT_IN_HISTORY." --permission-mode bypassPermissions
grep -c "<canary>" ~/.claude/projects/*/"$SID".jsonl
```

Turn 1 proves the content reaches the model, turn 2 proves it persists, and the
`grep` shows the form it takes on disk.

**Two traps, both hit while establishing the above.** `claude -p --continue`
resumed a *different* conversation than intended and produced an answer that
looked like a real result — always pin `--session-id` / `--resume` and verify
with a control question ("what did you just reply?") before trusting a negative.
And grepping `~/.claude/projects` for the canary matched the *driving* session's
own transcript, because that conversation quotes the value too — always grep the
specific session file, never the whole tree.

## Tools vs resources: the boundary is softer than the spec implies

"Application-controlled" reads as *the model cannot reach a resource*. In Claude
Code that is false. Given no URI at all — "this server is connected, find a
resource that looks like an identity card and read it" — the model listed the
server's resources, picked `probe://card` over `ui://probe/panel`, and returned
the canary. The host bridges resources to the model with built-in list/read
tools, so the model can reach them unaided.

The distinction that survives contact with reality is **discoverability**, not
access:

| | Tools | Resources |
|---|---|---|
| What the model is shown | name, description, input schema, in its tool catalogue | not in the catalogue; it must go looking |
| How it knows to use one | the description is an advertisement | no such prompt; it has to infer |
| Who picks the specific item | the model composes the arguments | usually the user or app (`@` mention, picker) |

So a tool is a capability *pushed at* the model; a resource is content *sitting
there* for someone to fetch. The model can fetch it, but nothing tells it to.

For a file-reading feature that means: a **tool** `read_file(path)` when the
model should decide which file and when (agentic work), a **resource**
`file:///{path}` when a human should choose what is relevant.

**Default to tools.** Not because resources are worse, but because tools work in
every host measured, while resources work in some and only where the host ships
a picker or mention UI. Add a resource when a human genuinely should do the
choosing *and* the target host supports it — and note that is additive, not a
substitute: the same data can reasonably be both a tool (for the agent) and a
resource (for the person), because they serve different actors.

For anything ChatGPT-facing the question is moot: it consumes no data resources,
so everything must be a tool.

## Scope

Measured on Claude Code 2.1.251. Other hosts may expand a mention eagerly rather
than lazily; the method above settles it in two commands. Irrelevant to ChatGPT,
which does not consume data resources at all — see `primitive-support.md`.
