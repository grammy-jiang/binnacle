Binnacle Deferred Decisions
===========================

:Status: Owner-approved deferral register
:Depends on: ``design-principles.rst``, ``bootstrap-v1.rst``, and ``target-architecture.rst``
:Purpose: Prevent non-blocking work from delaying the first ChatGPT self-hosting milestone

Purpose
-------

This document records design and implementation questions that are intentionally not
required before Bootstrap V1 crosses the self-hosting threshold.

A deferred item is not forgotten. It is postponed because one of the following is true:

* it does not block ChatGPT self-development;
* the correct decision depends on real Raspberry Pi or real ChatGPT evidence;
* a mature external solution should be investigated before Binnacle builds anything;
* the requirement belongs to production/release maturity rather than bootstrap;
* the target architecture already contains a stable seam, so implementation can wait.

Reopen a deferred item only when an observed requirement, failure, measured bottleneck,
security finding, host capability, or release milestone makes it relevant.

1. Advanced command sandbox implementation
-------------------------------------------

Deferred
~~~~~~~~

Selection and implementation of namespaces, seccomp, Bubblewrap/NsJail, Landlock,
AppArmor/SELinux, detailed cgroup policy, syscall allowlists, and equivalent hardening.

Bootstrap position
~~~~~~~~~~~~~~~~~~

Use separate executor identity, protected broker/control-plane separation, explicit
argv/cwd/environment, durable supervision, limits, and credential isolation. Normal
development Internet/LAN access remains available.

Reopen when
~~~~~~~~~~~

* real self-hosting is working;
* adversarial tests identify an actionable escape path;
* production support is approaching;
* a supported device profile requires a frozen sandbox security claim.

2. Interactive PTY and terminal reattachment
---------------------------------------------

Deferred
~~~~~~~~

Persistent PTY sessions, terminal resize/control, reattachment after MCP restart, and
interactive workflows such as REPLs, GDB, or ``git rebase -i``.

Bootstrap position
~~~~~~~~~~~~~~~~~~

Use deterministic non-interactive stdin/stdout/stderr process execution.

Reopen when
~~~~~~~~~~~

A real ChatGPT development workflow cannot be completed reasonably without interactive
terminal semantics.

3. Full MCP Resources/Prompts/Tasks/subscriptions/MRTR surface
---------------------------------------------------------------

Deferred
~~~~~~~~

Making every modern MCP primitive production-ready before the first connection.

Bootstrap position
~~~~~~~~~~~~~~~~~~

Tools + structured results are sufficient to cross the self-hosting threshold. Server
may probe newer capabilities.

Reopen when
~~~~~~~~~~~

Real ChatGPT is connected and the compatibility profile can test the actual behaviour of
Resources, Prompts, Tasks, subscriptions/notifications, MRTR, caching, and list-change
semantics.

4. Exact production OAuth/OIDC architecture
-------------------------------------------

Deferred
~~~~~~~~

Choosing and deploying a long-term authorisation server/provider topology.

Bootstrap position
~~~~~~~~~~~~~~~~~~

Use the standard/host-supported authentication path needed for the real development
ChatGPT profile and expose safe compatibility diagnostics.

Reopen when
~~~~~~~~~~~

Real-host tests establish the exact authentication context, refresh/session behaviour,
and controller identity available to Binnacle.

5. Tunnel setup automation and alternate providers
---------------------------------------------------

Deferred
~~~~~~~~

Fully automated OpenAI Secure MCP Tunnel setup plus Cloudflare/Tailscale provider
management.

Bootstrap position
~~~~~~~~~~~~~~~~~~

A manual/configuration-assisted working private connection is sufficient.

Reopen when
~~~~~~~~~~~

ChatGPT is connected and can improve the setup workflow from a known-good endpoint, or
multiple connectivity providers become a real user requirement.

6. STDIO and multiple local MCP clients
---------------------------------------

Deferred
~~~~~~~~

First-class STDIO profiles for Claude Code, Codex, GitHub Copilot, and simultaneous
HTTP/STDIO processes.

Bootstrap position
~~~~~~~~~~~~~~~~~~

One ChatGPT controller over Streamable HTTP.

Reopen when
~~~~~~~~~~~

The HTTP self-hosting loop is stable and a local AI client is ready for integration.
Then validate shared-state, reservation, idempotency, and audit correctness across
multiple Binnacle processes.

7. Multi-controller authorisation
---------------------------------

Deferred
~~~~~~~~

Complex RBAC/scopes/policies for multiple controllers.

Bootstrap position
~~~~~~~~~~~~~~~~~~

One authenticated owner/ChatGPT controller with a minimal deterministic local policy.

Reopen when
~~~~~~~~~~~

A second real controller is connected or a production deployment needs different
privilege classes.

8. Full policy-engine technology selection
------------------------------------------

Deferred
~~~~~~~~

Selecting the long-term general-purpose policy engine, such as OPA/Rego, Cedar, or
another mature policy technology.

Bootstrap position
~~~~~~~~~~~~~~~~~~

Use a small deterministic evaluator behind a stable ``PolicyEngine`` interface.
Operation contracts remain the maximum authority boundary.

Reopen when
~~~~~~~~~~~

Real multi-controller/resource/role/policy complexity makes the bootstrap evaluator
insufficient. Selection must be driven by actual policy requirements, auditability,
performance, language/tooling maturity, and Raspberry Pi operational cost.

9. Hardware capability implementation breadth
---------------------------------------------

Deferred
~~~~~~~~

Complete GPIO/I2C/SPI/UART/PWM/camera/touch-display and official/third-party hardware
support before self-hosting.

Bootstrap position
~~~~~~~~~~~~~~~~~~

Preserve the Tier-1/Tier-2/Tier-3 architecture and dependency-installation principles,
but implement only hardware needed by the development Pi to operate normally.

Reopen when
~~~~~~~~~~~

ChatGPT is self-hosting and the owner connects or requests a specific hardware
capability. Tier 1/2 should then be implemented as first-class Binnacle knowledge.

10. Third-party plugin/extension runtime
----------------------------------------

Deferred
~~~~~~~~

A public plugin manager, marketplace, in-process plugin API, or full out-of-process
extension SDK.

Bootstrap position
~~~~~~~~~~~~~~~~~~

Keep adapter/capability boundaries stable. Selected integrations can remain trusted
Binnacle code.

Reopen when
~~~~~~~~~~~

A real Tier-3/vendor integration needs independent distribution or the repository gains
external extension developers.

11. Advanced source-code search and code intelligence
------------------------------------------------------

Deferred
~~~~~~~~

Tree-sitter frameworks, semantic indexing, symbol databases, vector search/RAG, or a
Binnacle-specific repository indexing engine.

Bootstrap position
~~~~~~~~~~~~~~~~~~

Provide only file discovery and bounded text/regex search through a mature existing
solution behind a small search abstraction.

Reopen when
~~~~~~~~~~~

Real self-development demonstrates a measurable limitation. Investigate mature
open-source solutions before implementing custom indexing.

12. Structured/AST source editing
---------------------------------

Deferred
~~~~~~~~

Language-aware AST rewriting or refactoring infrastructure.

Bootstrap position
~~~~~~~~~~~~~~~~~~

Full normal file create/write/patch/move/delete permissions in the authorised Binnacle
source workspace.

Reopen when
~~~~~~~~~~~

A real development workflow shows that text/file editing is insufficient and an
existing mature structural-editing solution can be integrated safely.

13. Docker/Podman development-environment support
--------------------------------------------------

Deferred
~~~~~~~~

Container-aware workspace/environment orchestration.

Bootstrap position
~~~~~~~~~~~~~~~~~~

Each project uses its own native isolated development environment. Python uses a
project-local environment. Containers are not required.

Reopen when
~~~~~~~~~~~

A project explicitly requires containers or a measured isolation/portability need
outweighs the added hardware/network/runtime complexity.

14. Alternative Git backend
---------------------------

Deferred
~~~~~~~~

pygit2/libgit2 as a general replacement or secondary backend.

Bootstrap position
~~~~~~~~~~~~~~~~~~

Use official Git CLI behind a typed adapter.

Reopen when
~~~~~~~~~~~

Git object-database inspection, massive history/tree traversal, or another measured
workload demonstrates a concrete benefit from libgit2/pygit2.

15. GitHub-native API inside Binnacle
-------------------------------------

Deferred
~~~~~~~~

First-class issue/PR/review/merge/GitHub Actions APIs implemented by Binnacle.

Bootstrap position
~~~~~~~~~~~~~~~~~~

Binnacle handles local Git. ChatGPT's existing GitHub integration handles GitHub-host
workflow operations.

Reopen when
~~~~~~~~~~~

A local-only or offline architecture requires Binnacle to own these GitHub operations,
or ChatGPT's external GitHub integration proves insufficient.

16. Alternative system-management backends
------------------------------------------

Deferred
~~~~~~~~

Replacing CLI adapters with direct systemd D-Bus, netlink, package-manager libraries,
or other direct APIs.

Bootstrap position
~~~~~~~~~~~~~~~~~~

Use native Linux CLI/system mechanisms behind typed capability adapters.

Reopen when
~~~~~~~~~~~

A direct API provides measurable reliability, event, structure, performance, or security
benefit for a real operation.

17. Alternative privileged-broker implementation language
----------------------------------------------------------

Deferred
~~~~~~~~

Rust/C/another language for the privileged broker.

Bootstrap position
~~~~~~~~~~~~~~~~~~

Python is acceptable behind the language-neutral Unix-socket protocol.

Reopen when
~~~~~~~~~~~

Security review, dependency minimisation, memory-safety analysis, or performance
measurement shows a concrete benefit.

18. Alternative executor implementation
----------------------------------------

Deferred
~~~~~~~~

A custom native executor daemon, direct D-Bus-only implementation, or another execution
runtime.

Bootstrap position
~~~~~~~~~~~~~~~~~~

Use the minimal Python/systemd-backed supervisor that satisfies durable process
requirements.

Reopen when
~~~~~~~~~~~

Real workloads expose correctness, lifecycle, isolation, PTY, or performance limitations.

19. PostgreSQL or another database
----------------------------------

Deferred
~~~~~~~~

Replacing SQLite with PostgreSQL, LMDB, RocksDB, or another persistence engine.

Bootstrap position
~~~~~~~~~~~~~~~~~~

SQLite + SQLAlchemy + Alembic on local storage with WAL/FULL durability.

Reopen when
~~~~~~~~~~~

Measured concurrency, data volume, multi-process write contention, operational recovery,
or future fleet architecture exceeds SQLite's practical envelope.

20. Advanced result retention
-----------------------------

Deferred
~~~~~~~~

Compression, deduplication, content-addressed blobs, external object storage, complex
retention policies, or remote result archives.

Bootstrap position
~~~~~~~~~~~~~~~~~~

Filesystem payloads + SQLite references + bounded quotas/retention.

Reopen when
~~~~~~~~~~~

Real operation output creates material storage cost, retention latency, or duplication
problems.

21. General event framework breadth
-----------------------------------

Deferred
~~~~~~~~

Full inotify/udev/netlink/journald/hardware event integration before self-hosting.

Bootstrap position
~~~~~~~~~~~~~~~~~~

Implement operation lifecycle events needed to monitor development processes. Polling is
an acceptable fallback.

Reopen when
~~~~~~~~~~~

A requested hardware/system monitoring capability needs native event-driven behaviour.

22. Performance tuning
----------------------

Deferred
~~~~~~~~

Aggressive Uvicorn worker tuning, parser/event-loop benchmarks, SQLite pragma changes,
cache tuning, and other performance optimisation.

Bootstrap position
~~~~~~~~~~~~~~~~~~

Use conservative reasonable defaults and expose metrics.

Reopen when
~~~~~~~~~~~

ChatGPT can benchmark real MCP workloads on the real Pi and identify a measured
bottleneck. Correctness/durability remains higher priority.

23. Multi-worker HTTP scaling
-----------------------------

Deferred
~~~~~~~~

More than one Uvicorn worker.

Bootstrap position
~~~~~~~~~~~~~~~~~~

One worker for compatibility and simple state/session behaviour.

Reopen when
~~~~~~~~~~~

The actual ChatGPT profile is proven modern/stateless for the relevant path and
cross-process Binnacle state/metrics/audit coordination has been validated.

24. External observability infrastructure
-----------------------------------------

Deferred
~~~~~~~~

Prometheus server, Grafana, Loki, OpenTelemetry collector, ELK, or another mandatory
observability service.

Bootstrap position
~~~~~~~~~~~~~~~~~~

structlog + journald + local lightweight metrics + MCP/CLI diagnostics.

Reopen when
~~~~~~~~~~~

A production or multi-device deployment needs external monitoring/aggregation.

25. Hardware-backed credential storage
---------------------------------------

Deferred
~~~~~~~~

TPM-bound credentials, hardware tokens, or other advanced key protection.

Bootstrap position
~~~~~~~~~~~~~~~~~~

Dedicated device credentials, systemd credential mechanisms where useful, and
non-exportable agent/broker use.

Reopen when
~~~~~~~~~~~

Production threat model, hardware availability, or credential-risk review requires
stronger local extraction resistance.

26. Strong external audit anchoring
-----------------------------------

Deferred
~~~~~~~~

TPM signatures, remote immutable copies, transparency receipts, external timestamping,
or independent audit anchors.

Bootstrap position
~~~~~~~~~~~~~~~~~~

Local append-only SHA-256 integrity-linked journal with honest local-threat claims.

Reopen when
~~~~~~~~~~~

Production audit requirements need evidence against a fully compromised root host or
independent historical verification.

27. Comprehensive backup product
--------------------------------

Deferred
~~~~~~~~

Scheduled full backups, remote backup storage, sophisticated retention, restore
orchestration, and disaster-recovery automation.

Bootstrap position
~~~~~~~~~~~~~~~~~~

Git for source recovery plus lightweight local control-plane checkpoints around risky
self-management changes. SSH/local console remains break-glass recovery if Binnacle will
not start.

Reopen when
~~~~~~~~~~~

Production devices contain durable state whose loss exceeds the bootstrap/local recovery
assumptions.

28. Secondary autonomous recovery plane
---------------------------------------

Deferred
~~~~~~~~

A second remote control server capable of repairing Binnacle when Binnacle itself is
completely dead.

Bootstrap position
~~~~~~~~~~~~~~~~~~

Accept SSH/local console + known-good Git revision as break-glass recovery.

Reopen when
~~~~~~~~~~~

The owner requires unattended remote recovery or a production Pi cannot tolerate manual
intervention.

29. Production packaging implementation
----------------------------------------

Deferred
~~~~~~~~

Building/publishing DEB, RPM, PyPI artifacts during ordinary self-development.

Bootstrap position
~~~~~~~~~~~~~~~~~~

Run from the source checkout/project environment.

Reopen when
~~~~~~~~~~~

The owner explicitly declares Binnacle stable and sufficiently feature-complete for the
first supported release.

30. Production rollout/update system
------------------------------------

Deferred
~~~~~~~~

Canary rollout, automatic upgrades, rollback orchestration, staged production fleets,
and production update channels.

Bootstrap position
~~~~~~~~~~~~~~~~~~

Development Pi updates through Git/source workflow and controlled restart.

Reopen when
~~~~~~~~~~~

At least one separate production Raspberry Pi exists and supported releases begin.

31. Full distro/architecture support matrix
-------------------------------------------

Deferred
~~~~~~~~

Claiming Raspberry Pi OS/Debian/Ubuntu/Fedora/RHEL/Rocky and multiple Pi generations/
architectures before they have real-device evidence.

Bootstrap position
~~~~~~~~~~~~~~~~~~

One 64-bit development Pi reference profile.

Reopen when
~~~~~~~~~~~

Additional physical devices/OS profiles are available for acceptance tests or a real
user requirement targets them.

32. 32-bit ARM support
----------------------

Deferred
~~~~~~~~

``armhf``/32-bit Raspberry Pi runtime support.

Bootstrap position
~~~~~~~~~~~~~~~~~~

64-bit ARM only on the reference device.

Reopen when
~~~~~~~~~~~

A real target Pi requires 32-bit support and dependency/native-wheel feasibility has been
validated.

33. Python 3.14 public support
------------------------------

Deferred
~~~~~~~~

Advertising Python 3.14 as supported.

Bootstrap position
~~~~~~~~~~~~~~~~~~

3.11-3.13 support policy; 3.14 may be an experimental/non-blocking test lane.

Reopen when
~~~~~~~~~~~

Required upstream dependencies officially support it and Binnacle's full test matrix
passes.

34. Documentation hosting
-------------------------

Deferred
~~~~~~~~

GitHub Pages, Read the Docs, or another public Sphinx hosting provider.

Bootstrap position
~~~~~~~~~~~~~~~~~~

Write maintainable reStructuredText/Sphinx-oriented source documentation in-repository.

Reopen when
~~~~~~~~~~~

A public supported release needs published documentation.

35. Contributor/release governance expansion
---------------------------------------------

Deferred
~~~~~~~~

Extensive external-contributor governance, release committees, CODEOWNERS structure, or
enterprise contribution policy beyond what the repository currently needs.

Bootstrap position
~~~~~~~~~~~~~~~~~~

Keep the development workflow reviewable, CI-backed, and Git recoverable.

Reopen when
~~~~~~~~~~~

External contributor volume or supported-release governance creates a concrete need.

36. Local GUI/dashboard
-----------------------

Deferred / outside current product direction
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A Binnacle web dashboard or separate owner-facing GUI.

Bootstrap position
~~~~~~~~~~~~~~~~~~

ChatGPT is the owner-facing reasoning/interface surface. Local CLI remains the operator
surface.

Reopen when
~~~~~~~~~~~

Only if a future owner workflow cannot be served by ChatGPT + CLI and a concrete product
requirement is accepted.

37. General REST control API
----------------------------

Closed / not planned for V1
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Do not duplicate MCP operations behind a parallel REST control surface.

Reopen when
~~~~~~~~~~~

Only if a real non-MCP remote client requirement appears and cannot reasonably use MCP
or the local CLI/internal IPC boundary.

38. Fleet reasoning/coordination inside Binnacle
-------------------------------------------------

Outside current core scope
~~~~~~~~~~~~~~~~~~~~~~~~~~

Each Binnacle instance manages one local device. ChatGPT coordinates multiple devices.

Reopen when
~~~~~~~~~~~

Only after an explicit product-scope change. Do not let fleet features leak into the
single-device self-hosting kernel by default.

39. Release autonomy
--------------------

Deferred
~~~~~~~~

ChatGPT autonomously deciding that a Binnacle build should become a supported public
release.

Bootstrap position
~~~~~~~~~~~~~~~~~~

No automatic release publication. Development may commit/push/PR/merge as authorised.

Reopen when
~~~~~~~~~~~

The project has a stable release policy and the owner explicitly defines what release
authority, approval, and evidence ChatGPT may use.

40. Deferral exit rule
----------------------

A deferred decision moves into active design only when all of the following are true:

#. a real objective or blocker exists;
#. current device/host/software evidence is collected;
#. mature standards/native/open-source options have been investigated;
#. the existing architectural seam is reviewed;
#. the smallest useful implementation is identified;
#. the change can be validated at the appropriate CI/real-device/real-host level.

If those conditions are absent, keep the item deferred and continue improving the
self-hosting kernel or another demonstrated capability instead.
