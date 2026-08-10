Binnacle Design Principles
==========================

:Status: Owner-approved design principles
:Applies to: Bootstrap development and later Binnacle evolution
:Primary objective: Enable ChatGPT to develop and improve Binnacle through Binnacle itself

Purpose
-------

This document records the durable design principles established during the Binnacle
technology-stack and architecture review. It is intentionally more stable than any
particular implementation choice.

The primary development objective is to cross the self-hosting threshold:

::

   ChatGPT
     -> connects to a development-only Raspberry Pi through Binnacle
     -> understands the Pi and the running Binnacle instance
     -> reads and modifies the Binnacle source workspace
     -> runs development, test, and diagnostic work
     -> manages Git changes
     -> restarts Binnacle
     -> reconnects
     -> verifies the new behaviour
     -> continues improving Binnacle

Once this loop works reliably, later capabilities should preferentially be developed
through that loop rather than being prerequisites for it.

1. Self-hosting is the bootstrap priority
-----------------------------------------

Bootstrap scope is decided by one question first:

**Does this capability block ChatGPT from connecting to the development Raspberry Pi
and developing Binnacle itself?**

If yes, the capability receives a concrete Bootstrap V1 design and implementation.
If no, it should normally be deferred until the self-hosting loop exists and real
device evidence is available.

This rule exists to prevent scope creep. Hardware breadth, production packaging,
advanced sandboxing, multi-controller support, plugin ecosystems, fleet management,
performance tuning, and similar capabilities must not delay the first working
self-development loop unless an observed dependency proves otherwise.

2. ChatGPT reasons; Binnacle executes deterministically
-------------------------------------------------------

ChatGPT is the sole reasoning, planning, diagnosis, and strategy-selection agent.
Binnacle is the deterministic device-side execution and observation boundary.

Binnacle should:

* expose current local facts;
* enforce explicit operation contracts and local policy;
* execute bounded operations;
* retain durable lifecycle and evidence;
* report uncertainty honestly.

Binnacle should not:

* interpret high-level objectives independently;
* invent plans or strategies;
* contain a competing local AI agent;
* silently expand an operation because an output, file, log, or external response
  appears to instruct it to do so.

3. Build the seam now; defer the implementation when possible
--------------------------------------------------------------

When a future replacement is plausible, establish a small stable abstraction now
without implementing every alternative.

Examples include:

* Git CLI first, with a backend seam that can later admit pygit2/libgit2;
* native Linux CLI tools first, with adapters that can later use D-Bus, netlink, or
  other direct APIs;
* a Python privileged broker first, with a language-neutral IPC contract that can
  later support a different implementation language;
* SQLite first, behind persistence boundaries that do not force every helper to
  understand the database schema;
* basic search first, behind an abstraction that can later integrate a mature
  indexing or code-intelligence solution.

The purpose of an abstraction is replaceability at a real boundary, not architecture
for its own sake.

4. Prefer standards, native mechanisms, and mature open source
--------------------------------------------------------------

Binnacle should not reimplement mature generic infrastructure without a Binnacle-
specific reason.

Preference order is generally:

#. current standard protocol or operating-system mechanism;
#. mature, maintained open-source implementation;
#. thin Binnacle adapter around that mechanism;
#. custom implementation only where Binnacle has a genuinely unique requirement.

Examples include official Git, systemd, journald, distro package managers, Linux
hardware subsystems, SQLite, OpenSSH/GPG agents, and mature repository-search tools.

For MCP, use the standard capabilities supported by the negotiated MCP revision and
actual host implementation. Do not invent a proprietary authentication protocol or a
parallel remote REST control API when the standard already provides the required
surface.

5. Real ChatGPT behaviour outranks assumptions about host support
-----------------------------------------------------------------

MCP specification support and ChatGPT product support are separate facts.

Binnacle should implement standards cleanly, but a feature is not considered supported
for the ChatGPT profile until it has been observed against the real host. The bootstrap
server must therefore expose safe compatibility and authentication diagnostics so
ChatGPT can inspect the actual connection and help improve Binnacle from evidence.

Modern MCP capabilities such as Resources, Prompts, Tasks, subscriptions, and related
extensions are target capabilities, but unverified host behaviour must not block the
initial Tools-based self-hosting path.

6. Capability does not mean ambient authority
---------------------------------------------

The product goal is broad capability: ChatGPT should ultimately be able to perform
software development, system administration, and hardware work on its dedicated Pi.
Broad capability does not require every process to possess every authority all the
time.

Authority is deliberately separated by intent and execution path.

Typical boundaries are:

* development workspace operations -> ordinary workspace authority;
* development commands -> unprivileged execution identity and supervisor;
* privileged host changes -> narrow privileged broker;
* Git authentication/signing -> non-exportable credential use;
* hardware effects -> hardware adapter, reservation, and device policy;
* Binnacle self-management -> explicit development/self-management path.

Tool visibility, Prompt selection, Resource existence, a model statement, or a
conversation identifier never grants authority by itself.

7. Workspace development and system administration are different domains
-------------------------------------------------------------------------

Normal software development occurs inside explicit workspaces. An authorised Binnacle
development session has broad normal developer authority over the Binnacle source
workspace: create, read, write, patch, move, delete, build, test, and perform ordinary
Git work.

System areas are not silently treated as extensions of a workspace. Changes to
protected configuration, services, packages, policy, credentials, the installed
control plane, or other privileged host state use explicit system/self-management
operations and the privileged path when required.

This distinction preserves the behaviour of a capable engineer without turning normal
source editing into unrestricted root filesystem access.

8. The main MCP process is not root
-----------------------------------

The network-facing MCP/application process runs unprivileged.

Bootstrap architecture already contains three process roles:

* the unprivileged Binnacle MCP/application process;
* an independent execution supervisor for ChatGPT-started development processes;
* a minimal privileged broker for the small set of root operations required by
  self-development.

The privileged broker exposes structured operations rather than an unrestricted root
shell. systemd owns service lifecycle, identities, sockets, cgroups, and journald
integration where appropriate.

9. Credentials are used, not disclosed
---------------------------------------

Reusable credentials are never ordinary model-visible data.

GitHub access and commit signing are separate authorities. A development Pi may use a
dedicated SSH identity for repository access and a separate GPG/OpenPGP signing identity
for signed Git commits and tags.

Credential-bearing operations should use credential references and brokers/agents so
ChatGPT and general-purpose child processes do not receive raw private keys, tokens, or
passwords.

Development commands may have normal Internet/LAN access, but network access does not
imply credential, privileged-IPC, or control-plane access.

10. Long-running work is durable and jointly supervised
-------------------------------------------------------

A long-running operation is not just a child process of the MCP HTTP server.

Separate these lifecycles:

::

   MCP Task when supported
       -> durable Binnacle operation_id
       -> independent execution supervisor/systemd execution domain
       -> local process tree

The Binnacle ``operation_id`` remains authoritative even when MCP Tasks are available.
Once an operation is acknowledged, restarting or crashing the MCP server must not make
that operation become unknown.

ChatGPT is expected to remember, monitor, inspect output from, and eventually tear down
the long-running work it starts. Binnacle independently remembers the same work and
acts as an assurance layer through durable state, notifications where supported,
reconnect reconciliation, and disruptive-action preflight checks.

No process should disappear silently. Power loss, reboot, OOM, kernel failure, or other
external events can still terminate work, but Binnacle must preserve or reconstruct an
explicit completed, failed, cancelled, interrupted, or uncertain state whenever
possible.

11. Disruptive actions perform preflight
----------------------------------------

Before restart, shutdown, reboot, or another disruptive lifecycle action, Binnacle
checks its durable operation registry and reports relevant outstanding work.

The response should identify what is still running, current progress/output, and the
predicted impact of the requested disruption. ChatGPT should normally complete,
stop, tear down, or otherwise account for outstanding work before proceeding.

An operation being active does not automatically prohibit a restart if the operation
is independently supervised and known to survive. The requirement is awareness and an
explicit decision, not a global stop-the-world lock.

12. Development mode is a temporary authorised session
-------------------------------------------------------

Development diagnostics and self-management authority should not be a permanent
``development=true`` switch.

An explicit owner request to improve Binnacle constitutes authorisation to start a
bounded Binnacle development session. Once authorised, ChatGPT may perform the actual
mode transition, inspect richer diagnostics, modify the Binnacle source workspace,
run tests, restart development instances, reconnect, and verify the result without
asking the owner to repeat the same approval at every step.

The session ends or expires when the development task ends. Permanent safety baselines,
credential protections, and privileged boundaries remain in force during development.

13. Development diagnostics are broader than normal-user diagnostics
---------------------------------------------------------------------

Binnacle distinguishes what it records from what it exposes to ChatGPT.

Development sessions may expose broad Binnacle, MCP, journald, executor, broker,
performance, startup, and system diagnostics because ChatGPT needs evidence to debug
Binnacle itself.

Normal-user operation exposes a smaller diagnostic projection.

Neither profile exposes reusable secrets. Diagnostic queries remain structured,
bounded, redacted, and provenance-aware.

14. Project dependencies belong to the project that uses them
-------------------------------------------------------------

Binnacle runtime dependencies and development-project dependencies are separate.

If ChatGPT directly operates hardware through Binnacle, the required Python adapter is
part of Binnacle's own optional runtime capability. If ChatGPT develops a separate
program that uses the hardware, the dependency belongs to that project's isolated
development environment.

Each development project uses its own local environment where the ecosystem supports
it. For Python, an isolated project ``.venv`` managed with the project's native tooling
is the normal model. Docker/Podman are not Bootstrap requirements.

15. Hardware support knowledge and hardware dependency installation are separate
-------------------------------------------------------------------------------

Long term, Binnacle should understand Raspberry Pi board hardware and official Raspberry
Pi accessories deeply: detection, required drivers/system packages/Python dependencies,
setup, verification, and use.

Built-in knowledge does not mean those dependencies are installed by default. Optional
system and Python dependencies are installed only when the hardware capability is
explicitly enabled.

Third-party hardware support may be weaker and may fall back to ChatGPT research.
Hardware breadth does not block the initial self-hosting milestone.

16. Source development comes before distribution
-------------------------------------------------

During bootstrap and self-development, Binnacle runs from an explicit Git checkout and
its isolated development environment under systemd. ChatGPT edits that checkout, runs
quality/tests, commits, pushes, restarts the development service, reconnects, and
verifies the exact running Git revision.

Normal development and merges do not produce DEB/RPM/PyPI releases.

Release packaging begins only after an explicitly accepted stable, sufficiently
feature-complete milestone. Source state, GitHub state, release state, and installed
runtime state are related but never assumed to be identical.

17. Use real-device and real-host evidence
------------------------------------------

Testing has three evidence levels:

* ordinary automated CI for unit, property, schema, integration, and quality checks;
* real Raspberry Pi tests for Linux/systemd/filesystem/executor/broker/device behaviour;
* real ChatGPT tests for MCP discovery, authentication, Tasks/Resources/Prompts,
  notifications, confirmation behaviour, restart/reconnect, and other host-dependent
  semantics.

Mocks are useful but do not establish real-device or real-host support claims.

Bootstrap targets one real 64-bit Raspberry Pi development platform first. Broader Pi,
OS, architecture, and hardware profiles are added after evidence exists.

18. Durable state precedes consequential effects
------------------------------------------------

Binnacle creates the durable operation identity and admitted intent before a
consequential external process or effect starts. Executors and privileged brokers accept
only operation-bound requests and retain enough independent identity/evidence for
reconciliation.

SQLite and the operating system are not treated as one atomic transaction. Explicit
intermediate states plus deterministic reconciliation handle crashes between durable
state and real-world effects.

Retries use durable idempotency identities. A retry of the same logical operation
reconciles with the existing operation instead of blindly creating another effect.
When outcome cannot be established safely, Binnacle reports ``uncertain`` and does not
silently repeat the operation.

19. Logs, retained output, and audit are different things
---------------------------------------------------------

Diagnostic logs are for debugging and may be bounded or dropped under pressure.
Authoritative audit evidence must not silently disappear because a logging queue is
full.

Structured authoritative operation state belongs in SQLite. Large/streamable stdout,
stderr, results, and evidence payloads live in Binnacle-owned filesystem storage and
are referenced from structured state.

Audit uses a distinct append-only integrity-linked local journal in Bootstrap V1.
Large disposable result payloads may expire without erasing the durable audit fact that
the operation occurred and what result/evidence digest was observed.

20. Prefer durability over premature performance tuning
--------------------------------------------------------

Bootstrap correctness and recoverability are more important than small throughput wins.
SQLite uses a durable local profile, and Binnacle exposes enough metrics and diagnostics
for ChatGPT to benchmark the real Pi later.

Likewise, reasonable server/parser/event-loop defaults may be selected now, but
performance optimisation is deferred until real workload evidence exists.

21. Declarative contracts are source code, not executable policy scripts
------------------------------------------------------------------------

Operation/capability contracts use a hybrid design:

* declarative machine-readable definitions for stable semantics, authority metadata,
  lifecycle, MCP projection, and validation;
* typed Python for actual behaviour.

Declarative definitions are validated structurally and semantically, compiled/cached,
and loaded into immutable runtime registries. Normal request processing does not parse
YAML repeatedly.

The declarative format must remain data-oriented. Do not embed Python, Jinja, arbitrary
expressions, or a second programming language in operation definitions.

Bootstrap local authorisation remains intentionally small. A richer policy engine may
be adopted later behind a stable policy boundary when real requirements justify it.

22. Keep runtime architecture explicit and understandable
---------------------------------------------------------

Binnacle uses lightweight ports-and-adapters principles:

* MCP and CLI are thin interface adapters;
* application services orchestrate operations;
* domain/core types define Binnacle semantics independently of transport and concrete
  infrastructure;
* Git, filesystem, SQLite, systemd, package managers, executor IPC, privileged IPC,
  hardware, and similar mechanisms live behind typed replaceable boundaries.

Use ordinary Python composition and typed interfaces instead of a dependency-injection
framework. Enforce important dependency-direction rules mechanically with Import
Linter. Do not create layers that have no real architectural purpose.

23. Keep the bootstrap interface minimal but structurally honest
----------------------------------------------------------------

Bootstrap V1 requires only the capabilities necessary for the self-hosting loop:

* system/Binnacle inspection and compatibility diagnostics;
* Binnacle workspace file operations and basic search;
* durable command execution and operation status/output/cancellation;
* minimal Git workflow including signed commits and push;
* minimal privileged package/service/self-restart operations;
* development-session state and restart preflight.

Everything else should be deferred unless it becomes an observed blocker.

The final architecture should use MCP primitives according to their intended roles:
Tools for operations, Resources for addressable facts/state/context, Prompts for
user-selected workflows, Tasks for supported long-running request representation, and
notifications/subscriptions for meaningful state changes. None of these protocol
surfaces bypasses local authority checks.

24. Pre-1.0 evolution is allowed to break
-----------------------------------------

Before the first stable release, Binnacle may change experimental MCP contracts,
configuration, policy formats, internal IPC, database schemas, and other interfaces as
real ChatGPT/Raspberry Pi evidence improves the design.

Breaking development changes must still be explicit, versioned where appropriate,
migrated, tested, documented, and revalidated against the real host when relevant.

The first stable release establishes the compatibility boundary. Do not preserve a bad
bootstrap interface forever merely because it existed first.

25. Know when to stop designing
-------------------------------

A design question is complete enough for Bootstrap when ChatGPT has a clear path to:

#. connect to the development Pi;
#. understand the running Binnacle and local system;
#. inspect and modify the Binnacle repository;
#. run and monitor development work;
#. inspect logs and diagnostic evidence;
#. perform the required Git workflow;
#. restart safely;
#. reconnect;
#. verify the expected revision and behaviour;
#. continue developing Binnacle.

If a question does not prevent that loop and a stable architectural seam exists, defer
it. Future ChatGPT should make the detailed choice using real Raspberry Pi evidence,
current standards, and the principles in this document.
