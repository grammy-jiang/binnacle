Binnacle Phase 0 Detailed Implementation Plan
=============================================

:Phase: 0 -- Reconcile Bootstrap-blocking contracts
:Status: Ready for implementation
:Roadmap: ``../bootstrap-implementation-plan.rst``
:Index: ``index.rst``
:Primary objective: Remove contract contradictions that would block the Bootstrap self-hosting path
:Implementation scope: Contract/specification/fixture/validator changes only; no runtime application code

Purpose
-------

Phase 0 reconciles older V17 security and milestone contracts with the later
owner-approved Bootstrap decisions before any affected runtime capability is
implemented.

The phase is intentionally narrow. It does not weaken the permanent Binnacle boundaries
around credentials, protected control-plane state, privileged operations, devices, or
self-management. It changes two Bootstrap-blocking assumptions only:

#. authorised development commands may use ordinary outbound Internet and LAN
   application networking, including normal IPv4, IPv6, and DNS;
#. the Bootstrap self-hosting threshold includes the minimum signed Git/push and
   package/service/restart capabilities required to keep Binnacle self-development
   moving.

The phase also removes the older requirement that advanced kernel sandbox controls must
be completely proven before ``command_run`` can be considered usable for Bootstrap.
Those controls remain target hardening work; Bootstrap still requires a separate
unprivileged execution identity, process-tree/resource supervision, workspace
containment, and strict exclusion of Binnacle credentials and protected control-plane
IPC.

1. Governing source order
-------------------------

Implementation follows this precedence:

#. ``docs/design-principles.rst``;
#. ``docs/design.md``;
#. ``docs/bootstrap-v1.rst``;
#. ``docs/bootstrap-implementation-plan.rst``;
#. detailed security/policy contracts and fixtures;
#. ``docs/deferred-decisions.rst``;
#. ``docs/target-architecture.rst``.

The Phase 0 implementation must not reinterpret the owner-approved principles. It must
make the older detailed contracts consistent with them.

2. Roadmap exit gate
--------------------

Phase 0 is complete only when:

* the machine-readable command/capability policies no longer declare that Bootstrap
  development commands have no application-network access;
* the corresponding prose contracts describe the same profile-sensitive network model;
* the command-isolation and capability-composition fixtures test the new model;
* validator code rejects regression to the superseded Bootstrap assumptions;
* older prose that would prohibit the minimum Git push, package, service, or controlled
  restart path is reconciled where such contradictions actually exist;
* permanent credential/control-plane/privilege/device boundaries remain explicit;
* ``python scripts/validate_contracts.py`` passes;
* ``python scripts/validate_schema_instances.py`` passes;
* the repository ``Contract validation`` GitHub Actions workflow passes.

3. Explicit non-goals
---------------------

Phase 0 does **not** implement:

* the Python package skeleton;
* FastMCP or an MCP server;
* the execution supervisor;
* a privileged broker;
* real command execution;
* Git handlers or credential brokers;
* package/service/restart handlers;
* runtime policy evaluation;
* containers, namespaces, seccomp, Landlock, AppArmor, or SELinux;
* mediated HTTP egress implementation;
* a general policy engine;
* new MCP Tools;
* Tool-manifest promotion for later operational capabilities;
* new authentication behaviour;
* runtime tests on a Raspberry Pi.

If implementing Phase 0 appears to require one of those items, the work has crossed the
phase boundary and must stop.

4. Existing contradictions to reconcile
---------------------------------------

4.1 Command network authority
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The current ``docs/security/command-execution.md`` states that general command profiles
have denied IPv4, IPv6, and DNS and that external communication must use mediated
egress.

The current ``spec/policy/command-profiles.yaml`` encodes the same assumption:

::

   network:
     default: denied
     ipv4: denied
     ipv6: denied
     dns: denied
     unix_sockets: denied
     inherited_sockets: denied
     mediated_egress_only: true

and ``workspace-general-v1`` inherits that global network policy.

That conflicts with the owner-approved Bootstrap rule that an authorised development
command needs normal application networking for ordinary software-engineering work.

The replacement model is **profile-sensitive**:

* global/default command execution remains network-denied;
* ``workspace-general-v1`` explicitly opts into ordinary outbound application
  networking;
* ``workspace-check-v1`` inherits that normal development-network authority unless a
  later profile deliberately narrows it;
* Unix-domain control sockets and inherited sockets remain unavailable;
* raw/packet networking and network-administration capability remain denied;
* Binnacle credentials/credential agents remain unavailable;
* dedicated outcome-oriented credential operations remain preferred for credentialed
  effects such as repository push.

4.2 Capability-composition model
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The current ``docs/security/capability-composition.md`` and
``spec/policy/capability-zones.yaml`` treat **all** ``command_run`` network access as
forbidden and mediated-egress-only.

That must be narrowed. The corrected distinction is:

* ordinary application-network access by an authorised development process is allowed;
* Binnacle-managed protected/restricted data does not become available to that process;
* reusable credentials or credential-agent authority do not become available to that
  process;
* control-plane Unix sockets do not become available;
* device access does not become available;
* protected-data egress and credential-bearing effects still require their exact
  dedicated contracts/brokers where applicable.

The purpose of capability composition remains prevention of authority composition, not
prohibition of ordinary developer networking.

4.3 Advanced sandbox controls
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The current command-execution contract says the Tool remains unsupported unless every
mandatory isolation property, including syscall and mandatory-access-control policy, is
proven.

For Bootstrap this is superseded. The minimum Bootstrap execution boundary requires:

* a dedicated unprivileged execution identity;
* no Binnacle credential material;
* no privileged-broker or protected control-plane sockets;
* explicit executable/argv semantics;
* explicit workspace/working-directory authority;
* allowlisted environment construction;
* process-tree supervision and cleanup;
* bounded CPU/memory/PID/output/time resources;
* durable operation/reconciliation integration when Phase 7 is implemented;
* no raw/packet or network-administration privilege;
* no arbitrary device authority.

Seccomp/MAC/namespace hardening remains a target-security workstream and must not be a
Bootstrap ``command_run`` promotion prerequisite.

4.4 Self-hosting capability scope
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Where older V17 text says repository push, package operations, or service/self-update
operations are categorically post-V1, reconcile it to the narrow Bootstrap rule:

* signed commit and feature-branch push are required;
* one specifically requested development OS-package installation operation is allowed
  when it is genuinely required to unblock development;
* Binnacle service inspection/restart is required;
* controlled Binnacle restart is required;
* a generic root shell, arbitrary package-management shell, production rollout system,
  autonomous update framework, and fleet update mechanism remain deferred.

The implementation must change only contradictory text/specifications discovered in the
current tree. Do not rewrite already-correct Bootstrap documents merely for wording
uniformity.

5. Files to modify
------------------

The implementation PR is expected to modify the following existing files.

5.1 Required files
~~~~~~~~~~~~~~~~~~

``docs/security/command-execution.md``
   Reconcile command-network semantics and Bootstrap sandbox gating. Bump the semantic
   contract version from ``1.1.0`` to ``1.2.0``.

``docs/security/capability-composition.md``
   Replace the universal "general command execution has no direct egress" statement
   with the profile-sensitive Bootstrap model. Bump the semantic contract version from
   ``1.1.0`` to ``1.2.0``.

``spec/policy/command-profiles.yaml``
   Encode global deny plus explicit development-profile application-network authority;
   encode the distinction between required Bootstrap isolation and deferred advanced
   hardening. Bump ``policy_version`` from ``1.1.0`` to ``1.2.0``. Keep
   ``schema_version`` at ``1.1`` unless implementation discovers an existing consumer
   that treats the serialization shape as version-locked.

``spec/policy/capability-zones.yaml``
   Make ``command_run`` network authority profile-sensitive while preserving protected
   data, credential, control-plane, and device restrictions. Bump ``policy_version``
   from ``1.1.0`` to ``1.2.0``.

``tests/fixtures/security/command-isolation.yaml``
   Replace network-denial fixture expectations for development profiles and add
   regression cases for the permanent denied boundaries. Update ``policy_version`` to
   ``1.2.0``.

``tests/fixtures/security/capability-composition.yaml``
   Replace the ``command-network-default-deny`` assumption with explicit default-profile
   deny plus development-profile application networking. Add composition-regression
   cases. Update ``policy_version`` to ``1.2.0``.

``scripts/validate_contracts.py``
   Add explicit cross-file Bootstrap invariants so future edits cannot silently restore
   the superseded assumptions.

5.2 Conditional files
~~~~~~~~~~~~~~~~~~~~~

The implementer must search the repository for contradictory statements about:

* ``command_run`` having no network authority;
* ``mediated_egress_only`` applying universally to development commands;
* syscall/MAC hardening being a Bootstrap support prerequisite;
* Git push being categorically deferred beyond Bootstrap;
* all package/service/restart operations being categorically deferred beyond Bootstrap.

Only directly contradictory current files should be modified. Likely candidates include
sections of ``docs/design.md`` and older detailed contracts referenced from it. Any such
change must preserve historical/target intent while adding an explicit Bootstrap
exception rather than silently deleting the target requirement.

``docs/design-principles.rst``, ``docs/bootstrap-v1.rst``, and
``docs/bootstrap-implementation-plan.rst`` are governing sources and should normally
remain unchanged in Phase 0 unless an actual internal contradiction is found.

6. Machine-readable command-profile design
------------------------------------------

6.1 Global network defaults
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Retain fail-closed defaults for command profiles that do not explicitly opt into
networking.

The policy should retain a global form equivalent to:

.. code-block:: yaml

   network:
     default: denied
     ipv4: denied
     ipv6: denied
     dns: denied
     unix_sockets: denied
     inherited_sockets: denied
     raw_packet: denied
     network_admin: denied
     mediated_egress_only: true

The exact field names may differ only if an existing schema/consumer requires a
compatible spelling. Do not represent permission through an ambiguous scalar such as
``network: true``.

6.2 Development-profile override
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``workspace-general-v1`` must explicitly state the Bootstrap development-network
capability rather than relying on an undocumented exception.

Preferred shape:

.. code-block:: yaml

   profiles:
     workspace-general-v1:
       command_run_visible: true
       command_run_allowed: true
       structured_argv_only: true
       network:
         mode: application
         ipv4: allowed
         ipv6: allowed
         dns: allowed
         unix_sockets: denied
         inherited_sockets: denied
         raw_packet: denied
         network_admin: denied
         mediated_egress_only: false
       inherits_global_devices: true
       inherits_global_credentials: true

``workspace-check-v1`` should inherit this profile and only narrow executables/resources
unless a test-specific reason requires narrower networking.

The implementation must choose either a nested ``network`` override or an equally
explicit profile field set. It must not rely on hidden Python logic because the policy
source is intended to be human/ChatGPT-reviewable.

6.3 Credential and control-plane invariants
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The following must remain denied for ``workspace-general-v1`` and
``workspace-check-v1``:

.. code-block:: yaml

   credentials:
     raw_credentials: denied
     credential_helpers: denied
     inherited_agents: denied

and equivalent restrictions for:

* Binnacle protected state;
* privileged-broker socket;
* Binnacle control-plane IPC;
* inherited sockets;
* arbitrary device nodes;
* raw packet capability;
* network administration capability.

Normal Internet/LAN access must not be encoded as an implication that those authorities
are granted.

6.4 Bootstrap versus target hardening
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The machine-readable policy must no longer make advanced syscall/MAC isolation a
Bootstrap support prerequisite.

Preferred representation is explicit rather than deletion. For example:

.. code-block:: yaml

   privilege:
     dedicated_unprivileged_identity: true
     no_new_privileges: true
     ambient_capabilities: none
     inheritable_capabilities: none
     setuid_setgid_gain: denied
     ptrace_outside_execution_domain: denied
     bpf: denied
     kernel_keyring: denied
     advanced_syscall_policy:
       bootstrap_required: false
       target_hardening: true
     mandatory_access_control:
       bootstrap_required: false
       target_hardening: true

If retaining the existing ``syscall_policy_required`` and
``mandatory_access_control_required`` keys for compatibility, they must not remain
``true`` in a way that validator/runtime semantics interpret as a Bootstrap gate.

7. Machine-readable capability-composition design
-------------------------------------------------

7.1 Correct ``command_run`` representation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Replace the current unconditional block:

.. code-block:: yaml

   command_run:
     network_available: false
     ...
     mediated_egress_only: true

with a profile-sensitive form. Preferred semantics:

.. code-block:: yaml

   command_run:
     network_authority: profile-defined
     bootstrap_development_application_network: allowed
     raw_credentials_available: false
     credential_helpers_available: false
     device_access_available: false
     local_control_sockets_available: false
     raw_packet_network_available: false
     network_admin_available: false
     protected_data_egress_requires_exact_contract: true
     credential_bearing_effect_requires_dedicated_operation: true

The exact YAML names may be adjusted for consistency, but the semantics above are
mandatory.

7.2 Forbidden-edge semantics
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Do not remove the existing protections for:

* untrusted content -> control-plane mutation;
* protected data -> model-visible result;
* protected data -> external effect without its exact contract;
* credential broker -> raw secret disclosure;
* untrusted content -> privileged/system/self-management effect without exact prepared
  authority;
* cross-controller/cross-destination reference reuse.

If the current ``mediated-egress`` zone is retained, clarify that it represents
Binnacle-mediated protected/outcome-oriented egress, not all TCP/UDP application traffic
originating from a development child process.

8. Prose contract changes
-------------------------

8.1 ``docs/security/command-execution.md``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The implementation should make the following section-level changes.

``Purpose``
   Remove the statement that the Tool is unsupported until every advanced isolation
   property is proven. Replace it with the minimum Bootstrap boundary and a statement
   that additional isolation can be promoted later.

``Filesystem Boundary``
   Preserve current workspace and protected-path constraints.

``Environment, Descriptors, and IPC``
   Preserve credential-agent, inherited-socket, D-Bus/container-engine, and protected
   local-socket restrictions. Clarify that these restrictions coexist with ordinary
   application networking.

``Network and Devices``
   Replace the universal network-denied block with default-deny plus explicit
   ``workspace-general-v1``/``workspace-check-v1`` application-network permission.
   Define allowed application networking as normal IPv4/IPv6/DNS client/server behaviour
   required for development, subject to explicit bind/exposure policy in later runtime
   phases. Keep devices denied.

``Privilege and Kernel Controls``
   Split Bootstrap-required controls from target hardening. No text may imply that
   seccomp/MAC/namespaces are prerequisites for the initial development executor.

``Profile Separation``
   Document the development-profile override and keep ``self-management`` hidden from
   ``command_run``.

``Tests``
   Replace IPv4/IPv6/DNS denial tests for development profiles with connectivity-allowed
   tests while keeping socket/credential/device/control-plane escape tests.

``Invariants``
   Replace "network denied" with the more precise invariant that development networking
   grants no credential/control-plane/device/raw-network authority.

8.2 ``docs/security/capability-composition.md``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``Purpose``
   Keep the untrusted-data/authority separation unchanged.

``Default-Denied Compositions``
   Remove the universal "general command execution to network" prohibition. Replace it
   with prohibitions on credential-bearing, protected-data, control-plane, device, and
   privileged composition.

``Mediated Egress``
   Clarify that the mediator is required for exact Binnacle-controlled egress contracts
   involving protected/restricted data or dedicated credential-bearing outcomes. It is
   not the only path for ordinary development-process application networking.

``Command and Credential Separation``
   Preserve all raw-credential prohibitions and state explicitly that direct development
   networking does not grant a credential broker.

``Tests`` and ``Invariants``
   Replace universal network denial with profile-sensitive network cases and permanent
   authority-separation cases.

9. Fixture changes
------------------

9.1 ``tests/fixtures/security/command-isolation.yaml``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Retain the canonical execution-ticket and digest-substitution cases unchanged except for
policy-version updates.

Replace or rename ``workspace-check-profile-consistent`` so that it expects:

.. code-block:: yaml

   expect:
     command_run_visible: true
     command_run_allowed: true
     ipv4: allowed
     ipv6: allowed
     dns: allowed
     unix_sockets: denied
     inherited_sockets: denied
     raw_credentials: denied
     device_default: denied

Replace the current negative ``ipv4-egress`` and ``ipv6-egress`` cases with positive
cases for the development profile. Add a DNS case.

Required positive cases:

``development-ipv4-application-network``
   A development profile may establish an ordinary TCP client connection.

``development-ipv6-application-network``
   A development profile may create/use an IPv6 application socket.

``development-dns-resolution``
   A development profile may perform normal resolver access.

Required negative cases:

``default-profile-network-denied``
   A profile with no explicit development-network override remains denied.

``development-unix-control-socket-denied``
   Ordinary development networking does not expose protected Unix-domain sockets.

``development-inherited-socket-denied``
   Parent/control-plane descriptors are not inherited.

``development-raw-packet-denied``
   Raw packet/network-admin authority remains unavailable.

``development-credential-agent-denied``
   SSH/GPG/other credential agents are unavailable to general commands unless a future
   dedicated operation explicitly provides an outcome-oriented authority.

Keep the existing device-node, fork/process-tree, aggregate-quota, cleanup-failure,
execution-ticket replay, digest-binding, and direct-subprocess-fallback cases.

9.2 ``tests/fixtures/security/capability-composition.yaml``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Replace ``command-network-default-deny`` with two cases:

``command-default-profile-network-deny``
   Confirms fail-closed default policy.

``development-command-application-network-allowed``
   Confirms the authorised development profile permits normal application networking
   while credential helpers, device access, and local control sockets remain false.

Add:

``development-network-does-not-grant-credential-broker``
   A network-capable development child cannot obtain or invoke reusable credential
   authority merely because it can reach a remote host.

``development-network-does-not-grant-protected-data``
   A network-capable command cannot receive a server-held restricted/protected data
   reference as readable bytes without its exact disclosure/operation contract.

Keep destination-binding, redirect, DNS-rebinding, provenance, prepared-operation,
credential-audience, and restricted-result fixtures; those remain relevant to the
mediated protected-data path.

10. Validator implementation
----------------------------

Phase 0 must add explicit semantic checks to ``scripts/validate_contracts.py`` rather
than relying only on humans to notice future contradictions.

10.1 New function: ``validate_bootstrap_command_profile_alignment``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Add a top-level validator with signature:

.. code-block:: python

   def validate_bootstrap_command_profile_alignment() -> None:
       ...

It loads:

* ``spec/policy/command-profiles.yaml``;
* ``spec/policy/capability-zones.yaml``;
* ``tests/fixtures/security/command-isolation.yaml``;
* ``tests/fixtures/security/capability-composition.yaml``.

The function appends errors through the existing ``fail(message: str) -> None`` helper.
It must not raise for ordinary validation failures.

Required invariants:

#. ``workspace-general-v1`` exists and is visible/allowed;
#. its effective network policy explicitly allows IPv4, IPv6, and DNS;
#. its effective policy explicitly denies Unix/control sockets, inherited sockets,
   raw-packet/network-admin authority, devices, raw credentials, helpers, and inherited
   credential agents;
#. ``workspace-check-v1`` inherits or explicitly preserves the same authority boundaries;
#. ``self-management`` keeps ``command_run_visible: false`` and
   ``command_run_allowed: false``;
#. capability composition declares command network authority as profile-sensitive rather
   than universally unavailable;
#. capability composition still denies raw credentials, credential helpers, devices,
   local control sockets, raw packet authority, and network-admin authority;
#. the command-isolation fixture contains the required positive and negative network
   regression cases;
#. the capability-composition fixture contains both default-deny and development-network
   cases.

10.2 Helper functions
~~~~~~~~~~~~~~~~~~~~~

Do not introduce a generic policy framework in the validator. Add only small pure helpers
if they reduce ambiguity, for example:

.. code-block:: python

   def _mapping(value: Any, *, context: str) -> dict[str, Any] | None:
       ...

   def _fixture_case_ids(document: Any) -> set[str]:
       ...

   def _profile_network_policy(policy: dict[str, Any], profile_id: str) -> dict[str, Any] | None:
       ...

If profile inheritance must be interpreted, support only the simple single-parent
inheritance shape already used by ``workspace-check-v1``. Do not build a runtime policy
resolver in Phase 0.

10.3 Self-hosting scope validator
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Add:

.. code-block:: python

   def validate_bootstrap_self_hosting_scope_alignment() -> None:
       ...

This validator should be conservative. It must not attempt semantic NLP over all prose.
It should enforce machine-readable invariants that exist in the tree and exact forbidden
legacy markers if specific contradictory phrases are known.

At minimum it should verify that the Bootstrap governing documents still contain the
required narrow capabilities:

* signed Git commit / branch push;
* specifically requested development OS-package installation;
* Binnacle service restart / controlled restart.

If no machine-readable Phase 0 source yet represents those capabilities, do not invent a
new operational manifest in Phase 0. Prose consistency remains review-enforced until the
later Git/self-management phases create their reviewed contracts.

10.4 ``main`` integration
~~~~~~~~~~~~~~~~~~~~~~~~~

Call both new validators from ``main()`` after YAML/JSON parse validation and before the
final error report:

.. code-block:: python

   validate_parse_and_schemas()
   validate_bootstrap_command_profile_alignment()
   validate_bootstrap_self_hosting_scope_alignment()
   validate_tool_manifest()
   ...

The exact ordering may differ if needed, but parse validation must occur before semantic
checks.

11. Schema-instance validator impact
------------------------------------

``scripts/validate_schema_instances.py`` should remain unchanged unless one of the policy
or fixture files is directly validated against a JSON Schema there.

The implementer must inspect it before editing. Do not add a new schema merely to make
Phase 0 look more formal if the current policy files intentionally use validator-enforced
shape.

If a relevant existing schema is found, update that schema and representative instances
as part of Phase 0 and document the reason in the implementation PR.

12. Versioning rules
--------------------

Phase 0 changes policy semantics, so use a minor semantic-version bump:

* ``docs/security/command-execution.md``: ``1.1.0`` -> ``1.2.0``;
* ``docs/security/capability-composition.md``: ``1.1.0`` -> ``1.2.0``;
* ``spec/policy/command-profiles.yaml``: ``policy_version 1.1.0`` -> ``1.2.0``;
* ``spec/policy/capability-zones.yaml``: ``policy_version 1.1.0`` -> ``1.2.0``;
* corresponding fixture ``policy_version`` values -> ``1.2.0``.

Do not bump unrelated MCP, audit, release, schema, or Tool-manifest versions.

13. Dependency impact
---------------------

Phase 0 adds **no runtime, build, or project dependency**.

The existing contract-validation workflow already installs:

* ``PyYAML==6.0.3``;
* ``jsonschema==4.26.0``.

The Phase 0 validator changes use only:

* the Python standard library;
* existing ``yaml`` loading infrastructure;
* existing ``jsonschema`` infrastructure if an existing schema is relevant.

Do not add Pydantic, pytest, Hypothesis, FastMCP, SQLAlchemy, or ``uv`` project metadata in
this phase. Those belong to later phases.

14. Implementation sequence
---------------------------

The Phase 0 implementation PR should be executed in this order:

#. search the current tree for all superseded network/sandbox/self-hosting statements;
#. record the exact contradictory files in the PR description;
#. update ``spec/policy/command-profiles.yaml`` first;
#. update ``spec/policy/capability-zones.yaml`` to the same authority model;
#. update both security prose contracts to match the machine-readable semantics;
#. update command-isolation fixtures;
#. update capability-composition fixtures;
#. reconcile any additional directly contradictory V17 prose found by the search;
#. add the two validator functions and minimal helpers;
#. run contract validation locally;
#. run representative schema-instance validation;
#. inspect the diff specifically for accidental weakening of credential/control-plane,
   device, privileged, or protected-data restrictions;
#. open the Phase 0 implementation PR and require review/CI before Phase 1 implementation
   work begins.

15. Exact search audit before editing
-------------------------------------

Before making contract changes, search at least these tokens/phrases across ``docs/``,
``spec/``, ``schemas/``, and ``tests/fixtures/``:

::

   mediated_egress_only
   network_available
   network: denied
   ipv4: denied
   ipv6: denied
   dns: denied
   syscall_policy_required
   mandatory_access_control_required
   command_run_supported
   command_run
   Git push
   push
   package
   service restart
   self-management

For each hit, classify it as one of:

``must-change``
   Directly contradicts the Bootstrap governing principles.

``target-valid``
   Describes a future hardening/production target and remains valid once labelled as such.

``unrelated``
   Uses the term in another contract and needs no change.

The implementation PR description should summarize this audit so reviewers can verify
that Phase 0 did not over-edit unrelated contracts.

16. Security invariants after reconciliation
--------------------------------------------

The following invariants are mandatory after Phase 0.

Development-network invariant
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

An authorised Bootstrap development command may use ordinary application networking,
but that permission alone grants no additional local authority.

Credential invariant
~~~~~~~~~~~~~~~~~~~~

General development commands receive no reusable Binnacle credentials, Git private-key
material, GPG private-key material, bearer tokens, password material, or credential-agent
authority.

Control-plane invariant
~~~~~~~~~~~~~~~~~~~~~~~

General development commands cannot reach Binnacle authentication, policy, audit,
recovery, privileged-broker, executor-control, or protected management IPC merely
because network access is enabled.

Device invariant
~~~~~~~~~~~~~~~~

Normal command networking grants no GPIO, I2C, SPI, UART, PWM, raw device-node, or
arbitrary device authority.

Network-privilege invariant
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Normal application networking is not raw/packet networking and does not grant
``CAP_NET_ADMIN``, ``CAP_NET_RAW``, BPF authority, namespace administration, or equivalent
host-network control.

Protected-data invariant
~~~~~~~~~~~~~~~~~~~~~~~~

A network-capable development process does not automatically receive server-held
restricted/protected data. Dedicated information/operation contracts still govern those
flows.

Self-management invariant
~~~~~~~~~~~~~~~~~~~~~~~~~

``command_run`` remains unavailable in the ``self-management`` profile. Privileged
self-management uses dedicated structured operations in Phase 9 rather than shell
escalation.

Hardening invariant
~~~~~~~~~~~~~~~~~~~

Deferring advanced seccomp/MAC/namespace hardening does not create a direct-subprocess
fallback in the MCP application process. Phase 7 must still use the independent
unprivileged executor boundary.

17. Test/fixture acceptance matrix
----------------------------------

+--------------------------------------------------+----------+-----------------------------------------------+
| Case                                             | Expected | Contract                                      |
+==================================================+==========+===============================================+
| Default command profile IPv4                    | denied   | fail-closed default                           |
+--------------------------------------------------+----------+-----------------------------------------------+
| Development profile IPv4                        | allowed  | Bootstrap development networking              |
+--------------------------------------------------+----------+-----------------------------------------------+
| Development profile IPv6                        | allowed  | Bootstrap development networking              |
+--------------------------------------------------+----------+-----------------------------------------------+
| Development profile DNS                         | allowed  | Bootstrap development networking              |
+--------------------------------------------------+----------+-----------------------------------------------+
| Development profile protected Unix socket       | denied   | control-plane separation                      |
+--------------------------------------------------+----------+-----------------------------------------------+
| Inherited network/control socket                 | denied   | descriptor separation                         |
+--------------------------------------------------+----------+-----------------------------------------------+
| Raw packet / network-admin capability            | denied   | privilege separation                          |
+--------------------------------------------------+----------+-----------------------------------------------+
| Raw credential material                         | denied   | credential separation                         |
+--------------------------------------------------+----------+-----------------------------------------------+
| Inherited SSH/GPG credential agent               | denied   | credential separation                         |
+--------------------------------------------------+----------+-----------------------------------------------+
| Arbitrary device node                            | denied   | hardware separation                           |
+--------------------------------------------------+----------+-----------------------------------------------+
| Self-management through ``command_run``          | denied   | dedicated privileged path                     |
+--------------------------------------------------+----------+-----------------------------------------------+
| Development process -> ordinary Internet/LAN API | allowed  | normal software-development authority         |
+--------------------------------------------------+----------+-----------------------------------------------+
| Development networking -> protected-data export  | denied   | capability-composition/information boundary   |
+--------------------------------------------------+----------+-----------------------------------------------+
| Development networking -> credential broker      | denied   | outcome-oriented credential operation required|
+--------------------------------------------------+----------+-----------------------------------------------+

18. Local validation commands
-----------------------------

The Phase 0 implementation must run the existing repository validation commands directly:

.. code-block:: console

   python scripts/validate_contracts.py
   python scripts/validate_schema_instances.py

If the repository pre-commit configuration is available and its dependencies can be
installed without introducing project metadata, also run the relevant existing hooks.
Do not create ``pyproject.toml`` or ``uv.lock`` in Phase 0 merely to run validation; those
belong to Phase 1.

19. Review checklist
--------------------

Reviewers should verify all of the following before approving the Phase 0 implementation
PR:

#. global/default command network remains fail-closed;
#. only explicit development profiles receive ordinary application networking;
#. IPv4, IPv6, and DNS are all represented, not an ambiguous single network boolean;
#. Unix/control sockets remain denied;
#. inherited sockets remain denied;
#. raw packet and network-admin authority remain denied;
#. raw credentials and inherited credential agents remain denied;
#. arbitrary devices remain denied;
#. ``self-management`` still cannot use ``command_run``;
#. protected/restricted-data rules remain intact;
#. mediated egress is narrowed, not deleted;
#. advanced sandbox hardening is deferred only for Bootstrap and not falsely described as
   permanently unnecessary;
#. minimum Git/package/service/restart self-hosting scope is not contradicted elsewhere;
#. policy/contract versions are coherent;
#. validator checks prevent regression;
#. fixtures cover both allowed networking and still-denied authority composition;
#. no runtime/application code is added.

20. Acceptance checklist
------------------------

Phase 0 planning is considered implemented when the subsequent contract-reconciliation
PR demonstrates:

.. code-block:: text

   [ ] Current-tree contradiction audit completed
   [ ] command-execution.md reconciled and versioned
   [ ] capability-composition.md reconciled and versioned
   [ ] command-profiles.yaml reconciled and versioned
   [ ] capability-zones.yaml reconciled and versioned
   [ ] command-isolation fixture reconciled
   [ ] capability-composition fixture reconciled
   [ ] validator regression checks added
   [ ] minimum Git/package/service/restart scope has no remaining direct contradiction
   [ ] permanent credential/control-plane/device/protected-data boundaries preserved
   [ ] validate_contracts.py passes
   [ ] validate_schema_instances.py passes
   [ ] GitHub Contract validation passes
   [ ] AI/human review comments addressed and resolved

21. Handoff to Phase 1
----------------------

Phase 1 detailed planning may become ``ready-to-design`` only after this Phase 0 detailed
plan is merged, as required by ``index.rst``.

Phase 1 implementation must not start on top of unreconciled command/security contracts.
The contract implementation produced from this plan is a prerequisite for later runtime
promotion of ``command_run`` and self-hosting operations, but Phase 1 itself remains the
project-skeleton phase and must not prematurely implement those operational capabilities.

22. Deferred decisions retained
-------------------------------

Phase 0 deliberately leaves these decisions for later evidence/phases:

* exact Phase 7 executor mechanism (for example systemd transient units versus another
  systemd-backed supervisor implementation);
* exact seccomp/MAC/namespace hardening profile;
* exact network bind/exposure policy for development servers;
* dedicated mediated HTTP implementation;
* Git credential-broker implementation;
* package-manager adapter implementation;
* privileged-broker IPC messages;
* host-confirmation behaviour for operational Tools;
* production update/rollback architecture;
* fleet or multi-device policy.

None of these is needed to make the current contracts internally consistent enough to
start Bootstrap implementation.
