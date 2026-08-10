Binnacle Bootstrap Implementation Index
=======================================

:Status: Active implementation-planning index
:Primary roadmap: ``../bootstrap-implementation-plan.rst``
:Scope: Bootstrap V1 detailed engineering plans

Purpose
-------

This directory turns the phase roadmap in ``bootstrap-implementation-plan.rst`` into
implementation-level engineering specifications that a coding agent can execute.

The roadmap answers **what to build, in what order, and what proves each phase complete**.
The documents indexed here answer **how the phase is implemented**: repository layout,
modules, classes, functions, typed interfaces, schemas, configuration, dependencies,
process boundaries, scripts, tests, and phase-specific acceptance evidence.

Governing rules
---------------

Detailed phase plans follow these rules:

#. ``design-principles.rst`` remains the governing decision filter.
#. ``design.md`` remains the root feature specification and vocabulary source.
#. ``bootstrap-v1.rst`` defines the owner-approved Bootstrap architecture and technology
   baseline.
#. ``bootstrap-implementation-plan.rst`` defines phase order and exit gates.
#. Detailed contracts, schemas, manifests, policy files, and fixtures constrain the
   relevant phase but do not expand Bootstrap scope by themselves.
#. ``deferred-decisions.rst`` prevents non-blocking work from entering Bootstrap.
#. Real Raspberry Pi and real ChatGPT evidence outranks assumptions when a detail depends
   on the host or device.

One phase per pull request
--------------------------

Each numbered phase receives its own detailed implementation-plan pull request. A later
phase document is not merged merely because its predecessor was drafted: each phase is
reviewed, corrected, validated by GitHub Actions, and merged separately.

The shared foundation documents may be updated separately when they affect every phase.
Implementation code should likewise prefer small vertical pull requests rather than one
large Bootstrap implementation change.

Plan status vocabulary
----------------------

``planned``
   The phase exists in the roadmap but has no merged detailed engineering plan yet.

``ready-to-design``
   The preceding design/evidence dependencies are sufficient to create the detailed
   engineering plan.

``provisional``
   Internal design can be specified, but one or more host/device-dependent details must
   be frozen after an earlier real-evidence phase.

``evidence-blocked``
   The plan must not be frozen until named Raspberry Pi or ChatGPT evidence exists.

``merged``
   The detailed implementation plan has passed review and CI and is authoritative for
   implementation, subject to the normal pre-1.0 evidence-driven revision process.

Phase map
---------

+-------+------------------------------------------------------+----------------------+----------------------------------------------+
| Phase | Planned detailed document                            | Initial status       | Evidence / dependency gate                   |
+=======+======================================================+======================+==============================================+
| 0     | ``phase-00-contract-reconciliation.rst``             | ready-to-design      | Owner-approved principles and current V17    |
|       |                                                      |                      | contracts                                    |
+-------+------------------------------------------------------+----------------------+----------------------------------------------+
| 1     | ``phase-01-project-skeleton.rst``                    | ready-to-design      | Phase 0 merged                               |
+-------+------------------------------------------------------+----------------------+----------------------------------------------+
| 2     | ``phase-02-readonly-mcp-server.rst``                 | planned              | Phase 1 merged                               |
+-------+------------------------------------------------------+----------------------+----------------------------------------------+
| 3     | ``phase-03-pi-chatgpt-validation.rst``               | planned              | Phase 2 merged                               |
+-------+------------------------------------------------------+----------------------+----------------------------------------------+
| 4     | ``phase-04-durable-operation-kernel.rst``            | provisional          | Phase 3 compatibility evidence for any       |
|       |                                                      |                      | host-facing projection                       |
+-------+------------------------------------------------------+----------------------+----------------------------------------------+
| 5     | ``phase-05-write-capability-probe.rst``              | evidence-blocked     | Phase 3 authentication/discovery/confirmation|
|       |                                                      |                      | evidence                                     |
+-------+------------------------------------------------------+----------------------+----------------------------------------------+
| 6     | ``phase-06-development-workspace.rst``               | provisional          | Phase 5 write/confirmation evidence          |
+-------+------------------------------------------------------+----------------------+----------------------------------------------+
| 7     | ``phase-07-execution-supervisor.rst``                | provisional          | Phase 4 durable lifecycle + Phase 3 host     |
|       |                                                      |                      | evidence                                     |
+-------+------------------------------------------------------+----------------------+----------------------------------------------+
| 8     | ``phase-08-git-development.rst``                     | provisional          | Workspace/executor foundation                |
+-------+------------------------------------------------------+----------------------+----------------------------------------------+
| 9     | ``phase-09-privileged-self-management.rst``          | provisional          | Durable operations, Git workflow, real Pi    |
|       |                                                      |                      | service evidence                             |
+-------+------------------------------------------------------+----------------------+----------------------------------------------+
| 10    | ``phase-10-self-hosting-acceptance.rst``             | evidence-blocked     | All prior Bootstrap phases implemented and   |
|       |                                                      |                      | real ChatGPT connected                       |
+-------+------------------------------------------------------+----------------------+----------------------------------------------+

Required structure of every detailed phase plan
-----------------------------------------------

Each detailed phase document should contain, where applicable:

#. objective, prerequisites, and exact roadmap exit gate;
#. explicit non-goals and deferred work;
#. technology/dependency changes introduced by the phase;
#. exact repository paths to create or modify;
#. package/module responsibilities and dependency direction;
#. domain types, enums, dataclasses, Pydantic models, and type aliases;
#. ``Protocol``/ABC ports and concrete adapter responsibilities;
#. important classes, constructors, functions, arguments, return types, errors, and side
   effects;
#. persistence schema, migrations, transactions, and indexes;
#. MCP Tool/contract/schema/manifest projection where the phase exposes Tools;
#. internal IPC messages and framing where processes cross a trust boundary;
#. configuration keys, types, defaults, security properties, and precedence;
#. CLI commands, setup/maintenance scripts, and systemd units where applicable;
#. logging, diagnostics, health/readiness, and error projection;
#. phase-specific security invariants;
#. unit, property, integration, system, real-Pi, and real-ChatGPT tests as applicable;
#. deterministic phase acceptance checklist;
#. unresolved/provisional items and the evidence required to freeze them.

Interface ownership
-------------------

A type or interface has one canonical owning module and one phase in which it is first
introduced. Later phase documents extend or consume it rather than defining competing
versions in parallel.

Host-dependent MCP behaviour must be labelled provisional until the relevant real
ChatGPT evaluation has been recorded. Internal boundaries that are already owner-approved
-- such as ports-and-adapters layering, SQLite ownership, executor/broker process
separation, and Unix-domain-socket IPC -- may be specified concretely before that host
evidence exists.

Dependency discipline
---------------------

Dependencies are added when the first implementing phase genuinely requires them, not
all at once because a later phase might use them.

Exact resolved versions belong in ``uv.lock``. Detailed plans specify the direct package,
required major/minor compatibility line where relevant, why it is needed, and whether it
is runtime, optional runtime, development, build, or test-only.

Mature native mechanisms remain preferred where the technology baseline already chose
them: Git CLI, systemd/journald, SQLite, OpenSSH/GPG mechanisms, distro package managers,
and ``ripgrep`` should not be replaced by custom Python frameworks without a concrete
Binnacle-specific reason.

Planning stop rule
------------------

Detailed planning is complete enough when the next phase can be implemented and tested
without making unresolved architectural decisions that block its roadmap exit gate.

Do not freeze post-Bootstrap architecture merely to make these documents exhaustive.
Once the real self-hosting loop works, future detailed design should preferentially be
created and validated through ChatGPT + Binnacle itself.
