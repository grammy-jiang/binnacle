Binnacle Bootstrap Implementation Index
=======================================

:Status: Detailed plans complete; repository implementation through Phase 10; live gates remain
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

Detailed-plan readiness and implementation/promotion readiness are intentionally
separate. When real host/device evidence cannot exist until an earlier planned phase is
implemented, a later phase may still receive a ``provisional`` detailed plan if the plan
freezes only evidence-independent architecture, contracts, deterministic algorithms,
security invariants, test machinery, and evidence procedures. Host/device-dependent
facts must remain explicit, unresolved decision points or conditional branches.

A provisional detailed plan does **not** promote runtime authority, does not convert an
unknown compatibility-profile field into support, and does not satisfy the phase's
implementation exit gate. The implementation or host-facing promotion remains blocked
until the named real evidence exists. This distinction allows the detailed planning
sequence to complete without fabricating observations that only a future implementation
run can produce.

Plan status vocabulary
----------------------

``planned``
   The phase exists in the roadmap but has no merged detailed engineering plan yet. A
   planned phase whose named dependency/evidence gate is not satisfied must wait unless
   the phase can legitimately be treated as ``provisional`` under the rule above.

``ready-to-design``
   The preceding design/evidence dependencies are sufficient to create the detailed
   engineering plan with no material host/device-dependent branch left open.

``provisional``
   A detailed plan may be created and merged before one or more named real evidence items
   exist, but only evidence-independent decisions may be frozen. Every host/device-
   dependent choice must be visibly conditional, must name the evidence that resolves it,
   and must fail closed at implementation/promotion time if that evidence is absent,
   expired, incomplete, or contradictory.

``evidence-blocked``
   Even an evidence-independent detailed plan would be materially misleading or unsafe;
   no numbered plan may be frozen until the named evidence exists. Use this status
   narrowly. Prefer ``provisional`` when a deterministic safe plan can be written without
   claiming the missing observation.

``merged``
   The detailed implementation plan has passed review and CI and is authoritative for
   the decisions it actually freezes, subject to explicit provisional evidence gates and
   the normal pre-1.0 evidence-driven revision process.

Phase map
---------

+-------+------------------------------------------------------+----------------------+----------------------------------------------+
| Phase | Planned detailed document                            | Initial status       | Evidence / dependency gate                   |
+=======+======================================================+======================+==============================================+
| 0     | ``phase-00-contract-reconciliation.rst``             | ready-to-design      | Owner-approved principles and current V17    |
|       |                                                      |                      | contracts                                    |
+-------+------------------------------------------------------+----------------------+----------------------------------------------+
| 1     | ``phase-01-project-skeleton.rst``                    | planned              | Phase 0 merged                               |
+-------+------------------------------------------------------+----------------------+----------------------------------------------+
| 2     | ``phase-02-readonly-mcp-server.rst``                 | planned              | Phase 1 merged                               |
+-------+------------------------------------------------------+----------------------+----------------------------------------------+
| 3     | ``phase-03-pi-chatgpt-validation.rst``               | planned              | Phase 2 merged                               |
+-------+------------------------------------------------------+----------------------+----------------------------------------------+
| 4     | ``phase-04-durable-operation-kernel.rst``            | provisional          | Phase 3 compatibility evidence for any       |
|       |                                                      |                      | host-facing projection                       |
+-------+------------------------------------------------------+----------------------+----------------------------------------------+
| 5     | ``phase-05-write-capability-probe.rst``              | provisional          | Phase 4 plan merged for drafting; Phase 4    |
|       |                                                      |                      | implementation exit plus real Phase 3 auth,  |
|       |                                                      |                      | discovery, and confirmation evidence gate    |
|       |                                                      |                      | implementation/promotion                     |
+-------+------------------------------------------------------+----------------------+----------------------------------------------+
| 6     | ``phase-06-development-workspace.rst``               | provisional          | Phase 5 plan may be merged for drafting;     |
|       |                                                      |                      | Phase 5 implementation exit and              |
|       |                                                      |                      | write-confirmation evidence gate             |
|       |                                                      |                      | operational promotion                        |
+-------+------------------------------------------------------+----------------------+----------------------------------------------+
| 7     | ``phase-07-execution-supervisor.rst``                | provisional          | Phase 4 plan may be merged for drafting;     |
|       |                                                      |                      | Phase 4 implementation exit plus real Phase 3|
|       |                                                      |                      | host evidence gates host-facing projection   |
+-------+------------------------------------------------------+----------------------+----------------------------------------------+
| 8     | ``phase-08-git-development.rst``                     | provisional          | Workspace/executor plans permit drafting;    |
|       |                                                      |                      | Phase 6 workspace and Phase 7 executor       |
|       |                                                      |                      | implementation exit gates plus their real    |
|       |                                                      |                      | predecessor evidence gate promotion          |
+-------+------------------------------------------------------+----------------------+----------------------------------------------+
| 9     | ``phase-09-privileged-self-management.rst``          | provisional          | Durable-operation/Git plans permit drafting; |
|       |                                                      |                      | Phase 4 durable-kernel and Phase 8 Git       |
|       |                                                      |                      | implementation exit gates plus real Pi       |
|       |                                                      |                      | service evidence gate privileged promotion   |
+-------+------------------------------------------------------+----------------------+----------------------------------------------+
| 10    | ``phase-10-self-hosting-acceptance.rst``             | provisional          | All prior plans may be merged provisionally; |
|       |                                                      |                      | acceptance requires all prior implementation |
|       |                                                      |                      | gates plus real ChatGPT                      |
+-------+------------------------------------------------------+----------------------+----------------------------------------------+

Current Phase 10 implementation state
-------------------------------------

The evidence-independent Phase 10 repository slice is implemented: frozen policy and
closed schemas, an authority-free evaluator, adversarial fixtures/property tests, exact
GitHub checkout attestation in every required CI job, and an operator/reviewer procedure.
The separate real ChatGPT-on-Pi acceptance campaign remains ``INCOMPLETE`` until it is run
with current predecessor promotion evidence.  Missing live evidence does not block the
repository implementation and does not count as Bootstrap ``PASS``.

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

For every ``provisional`` plan, the acceptance section must distinguish:

* plan acceptance -- review/CI proves the evidence-independent engineering specification
  is coherent and implementable;
* implementation promotion -- the named real evidence is present and current before any
  host-dependent capability or authority is exposed;
* phase exit -- the roadmap's real implementation/evidence gate passes.

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

Missing real host/device evidence does not by itself stop the **planning** sequence when
the next phase can be specified safely and provisionally. In that case, freeze the
invariant implementation structure, leave evidence-dependent choices explicit, and
continue to the next numbered plan. Stop only when even a provisional plan would require
inventing a host/device fact or making an unsafe architectural commitment.

Do not freeze post-Bootstrap architecture merely to make these documents exhaustive.
Once the real self-hosting loop works, future detailed design should preferentially be
created and validated through ChatGPT + Binnacle itself.
