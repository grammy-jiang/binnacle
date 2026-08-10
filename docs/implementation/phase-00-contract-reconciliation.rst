Binnacle Phase 0 Detailed Implementation Plan
=============================================

:Phase: 0 -- Reconcile Bootstrap-blocking contracts
:Status: merged
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

#. authorised development commands may use ordinary Internet and LAN application
   networking, including normal IPv4, IPv6, DNS, and loopback listeners used by local
   development servers;
#. the Bootstrap self-hosting threshold includes the minimum signed Git/push and
   package/service/restart capabilities required to keep Binnacle self-development
   moving.

The phase also removes the older requirement that advanced kernel sandbox controls must
be completely proven before ``command_run`` can be considered usable for Bootstrap.
Those controls remain target hardening work. Bootstrap still requires a separate
unprivileged execution identity, process-tree/resource supervision, workspace
containment, explicit authority boundaries, and strict exclusion of Binnacle credentials
and protected control-plane IPC.

This document describes the implementation work for Phase 0. It does not implement the
runtime application, executor, broker, Git service, or package/service operations.

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
make older detailed contracts consistent with them.

Two governing corrections are especially important:

* authorised Bootstrap development commands may use ordinary application networking;
* Bootstrap includes the minimum Git push, package, service, and controlled-restart
  capabilities required to reach the first self-hosting loop.

The Bootstrap baseline additionally requires development servers to bind to loopback by
default. Non-loopback/LAN exposure is a separate, explicit authority and must not be
inferred merely because application networking is allowed.

2. Roadmap exit gate
--------------------

Phase 0 is complete only when:

* machine-readable command/capability policies no longer declare that Bootstrap
  development commands have no application-network access;
* the corresponding prose contracts describe the same profile-sensitive network model;
* the loopback-default/explicit-exposure rule is represented consistently in the
  relevant policy, prose, fixtures, and validator requirements;
* command-isolation and capability-composition fixtures test the new model;
* validator code checks the semantic content of required fixture cases, not only their
  identifiers;
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
* runtime socket binding or network filtering;
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

The current ``spec/policy/command-profiles.yaml`` encodes the same assumption through a
global deny policy that ``workspace-general-v1`` inherits.

That conflicts with the owner-approved Bootstrap rule that an authorised development
command needs normal application networking for ordinary software-engineering work.

The replacement model is profile-sensitive:

* global/default command execution remains network-denied;
* ``workspace-general-v1`` explicitly opts into ordinary application networking;
* ``workspace-check-v1`` inherits that normal development-network authority unless a
  later profile deliberately narrows it;
* IPv4, IPv6, and DNS are allowed for the authorised development profile;
* loopback listener/server binds are allowed by default for development servers;
* wildcard or non-loopback listener exposure is denied by default and requires an
  explicit request/authority;
* Unix-domain control sockets and inherited sockets remain unavailable;
* raw/packet networking and network-administration capability remain denied;
* Binnacle credentials/credential agents remain unavailable;
* dedicated outcome-oriented credential operations remain preferred for credentialed
  effects such as repository push.

The distinction between **network use** and **network exposure** is normative. Permission
to use normal Internet/LAN application networking does not automatically authorise a
command to expose a listener on ``0.0.0.0``, ``::``, or another non-loopback address.

4.2 Capability-composition model
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The current ``docs/security/capability-composition.md`` and
``spec/policy/capability-zones.yaml`` treat all ``command_run`` network access as
forbidden and mediated-egress-only.

That must be narrowed. The corrected distinction is:

* ordinary application-network access by an authorised development process is allowed;
* loopback listeners are normal development authority;
* non-loopback/LAN listener exposure requires explicit authority;
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
* no arbitrary device authority;
* loopback-only development-server binding by default unless an explicit exposure
  request grants broader bind authority.

Seccomp/MAC/namespace hardening remains a target-security workstream and must not be a
Bootstrap ``command_run`` promotion prerequisite.

4.4 Self-hosting capability scope
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Where older V17 text says repository push, package operations, or service/self-update
operations are categorically post-V1, reconcile it to the narrow Bootstrap rule:

* signed commit and feature-branch push are required;
* one specifically requested development OS-package installation operation is allowed
  when genuinely required to unblock development;
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
   Reconcile command-network semantics, listener-binding semantics, and Bootstrap
   sandbox gating. Bump the semantic contract version from ``1.1.0`` to ``1.2.0``.

``docs/security/capability-composition.md``
   Replace the universal "general command execution has no direct egress" statement
   with the profile-sensitive Bootstrap model. Distinguish application networking from
   non-loopback listener exposure. Bump the semantic contract version from ``1.1.0`` to
   ``1.2.0``.

``spec/policy/command-profiles.yaml``
   Encode global deny plus explicit development-profile application-network authority,
   loopback-default binding, explicit non-loopback exposure authority, and the
   distinction between required Bootstrap isolation and deferred advanced hardening.
   Bump ``policy_version`` from ``1.1.0`` to ``1.2.0``. Keep ``schema_version`` at
   ``1.1`` unless implementation discovers an existing consumer that treats the
   serialization shape as version-locked.

``spec/policy/capability-zones.yaml``
   Make ``command_run`` network authority profile-sensitive while preserving protected
   data, credential, control-plane, listener-exposure, and device restrictions. Bump
   ``policy_version`` from ``1.1.0`` to ``1.2.0``.

``tests/fixtures/security/command-isolation.yaml``
   Replace network-denial fixture expectations for development profiles, add the
   loopback-default/non-loopback-explicit-exposure cases, and add regression cases for
   the permanent denied boundaries. Update ``policy_version`` to ``1.2.0``.

``tests/fixtures/security/capability-composition.yaml``
   Replace the ``command-network-default-deny`` assumption with explicit default-profile
   deny plus development-profile application networking. Add listener-exposure and
   composition-regression cases. Update ``policy_version`` to ``1.2.0``.

``scripts/validate_contracts.py``
   Add explicit cross-file Bootstrap invariants, including fixture-content assertions,
   so future edits cannot silently restore the superseded assumptions.

5.2 Conditional files
~~~~~~~~~~~~~~~~~~~~~

The implementer must search the repository for contradictory statements about:

* ``command_run`` having no network authority;
* ``mediated_egress_only`` applying universally to development commands;
* application networking implying unrestricted listener exposure;
* development servers being allowed to bind non-loopback without explicit exposure;
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
     listener_bind:
       loopback: denied
       non_loopback: denied
       explicit_exposure_required: true

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
         listener_bind:
           loopback: allowed
           non_loopback: explicit
           explicit_exposure_required: true
       inherits_global_devices: true
       inherits_global_credentials: true

``workspace-check-v1`` should inherit this profile and only narrow executables/resources
unless a test-specific reason requires narrower networking.

The implementation must choose either a nested ``network`` override or an equally
explicit profile field set. It must not rely on hidden Python logic because the policy
source is intended to be human/ChatGPT-reviewable.

The policy vocabulary must make these two cases distinguishable:

* ordinary local development server: loopback bind, no separate exposure authority;
* intentionally exposed development server: non-loopback bind only after an explicit
  operation/request grants the exposure.

Phase 0 defines the contract representation only. Runtime enforcement belongs to the
later command/executor phase.

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

If retaining existing ``syscall_policy_required`` and
``mandatory_access_control_required`` keys for compatibility, they must not remain
``true`` in a way that validator/runtime semantics interpret as a Bootstrap gate.

7. Machine-readable capability-composition design
-------------------------------------------------

7.1 Correct ``command_run`` representation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Replace the current unconditional network prohibition with a profile-sensitive form.
Preferred semantics:

.. code-block:: yaml

   command_run:
     network_authority: profile-defined
     bootstrap_development_application_network: allowed
     listener_bind_default: loopback
     non_loopback_listener_requires_explicit_exposure: true
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
* cross-controller/cross-destination reference reuse;
* general development-network permission -> implicit non-loopback listener exposure.

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
   Define allowed application networking as normal IPv4/IPv6/DNS client/server
   behaviour required for development. State normatively that development servers bind
   to loopback by default and that non-loopback/LAN exposure requires an explicit
   request/authority. Keep devices denied.

``Privilege and Kernel Controls``
   Split Bootstrap-required controls from target hardening. No text may imply that
   seccomp/MAC/namespaces are prerequisites for the initial development executor.

``Profile Separation``
   Document the development-profile override and keep ``self-management`` hidden from
   ``command_run``.

``Tests``
   Replace IPv4/IPv6/DNS denial tests for development profiles with
   connectivity-allowed tests while keeping socket/credential/device/control-plane
   escape tests. Add loopback-default and explicit-non-loopback-exposure cases.

``Invariants``
   Replace "network denied" with the more precise invariant that development networking
   grants no credential/control-plane/device/raw-network authority and no implicit
   non-loopback listener exposure.

8.2 ``docs/security/capability-composition.md``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``Purpose``
   Keep the untrusted-data/authority separation unchanged.

``Default-Denied Compositions``
   Remove the universal "general command execution to network" prohibition. Replace it
   with prohibitions on credential-bearing, protected-data, control-plane, device,
   privileged, and implicit listener-exposure composition.

``Mediated Egress``
   Clarify that the mediator is required for exact Binnacle-controlled egress contracts
   involving protected/restricted data or dedicated credential-bearing outcomes. It is
   not the only path for ordinary development-process application networking.

``Command and Credential Separation``
   Preserve all raw-credential prohibitions and state explicitly that direct development
   networking does not grant a credential broker.

``Listener Exposure``
   State that loopback listeners belong to ordinary development authority while a
   non-loopback/LAN listener requires an explicit exposure request/authority.

``Tests`` and ``Invariants``
   Replace universal network denial with profile-sensitive network cases, listener-bind
   cases, and permanent authority-separation cases.

9. Fixture changes
------------------

9.1 ``tests/fixtures/security/command-isolation.yaml``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Retain canonical execution-ticket, digest-substitution, device-node,
fork/process-tree, aggregate-quota, cleanup-failure, replay, digest-binding, and
direct-subprocess-fallback cases unless their policy-version metadata must change.

The development-profile consistency case must assert content equivalent to:

.. code-block:: yaml

   expect:
     command_run_visible: true
     command_run_allowed: true
     ipv4: allowed
     ipv6: allowed
     dns: allowed
     loopback_listener: allowed
     non_loopback_listener: explicit
     explicit_exposure_required: true
     unix_sockets: denied
     inherited_sockets: denied
     raw_credentials: denied
     device_default: denied

Required positive cases:

``development-ipv4-application-network``
   A development profile may establish an ordinary TCP client connection.

``development-ipv6-application-network``
   A development profile may create/use an IPv6 application socket.

``development-dns-resolution``
   A development profile may perform normal resolver access.

``development-loopback-listener-allowed``
   A development server may bind to ``127.0.0.1`` or ``::1`` without requesting broader
   exposure.

Required negative/conditional cases:

``default-profile-network-denied``
   A profile with no explicit development-network override remains denied.

``development-non-loopback-listener-requires-explicit-exposure``
   A bind to ``0.0.0.0``, ``::``, or a specific non-loopback/LAN address is not ordinary
   ambient development authority; it requires the explicit exposure request/authority.

``development-unix-control-socket-denied``
   Ordinary development networking does not expose protected Unix-domain sockets.

``development-inherited-socket-denied``
   Parent/control-plane descriptors are not inherited.

``development-raw-packet-denied``
   Raw packet/network-admin authority remains unavailable.

``development-credential-agent-denied``
   SSH/GPG/other credential agents are unavailable to general commands unless a future
   dedicated operation explicitly provides an outcome-oriented authority.

9.2 ``tests/fixtures/security/capability-composition.yaml``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Replace ``command-network-default-deny`` with explicit default and development cases.

Required cases:

``command-default-profile-network-deny``
   Confirms fail-closed default policy.

``development-command-application-network-allowed``
   Confirms the authorised development profile permits normal application networking
   while credential helpers, device access, and local control sockets remain false.

``development-loopback-listener-default``
   Confirms the development profile may bind a local development listener to loopback.

``development-non-loopback-listener-needs-explicit-exposure``
   Confirms application-network authority alone is insufficient for non-loopback/LAN
   listener exposure.

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

10.1 ``validate_bootstrap_command_profile_alignment``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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

Required policy invariants:

#. ``workspace-general-v1`` exists and is visible/allowed;
#. its effective network policy explicitly allows IPv4, IPv6, and DNS;
#. its listener policy allows loopback by default and requires explicit authority for
   non-loopback exposure;
#. its effective policy explicitly denies Unix/control sockets, inherited sockets,
   raw-packet/network-admin authority, devices, raw credentials, helpers, and inherited
   credential agents;
#. ``workspace-check-v1`` inherits or explicitly preserves the same authority
   boundaries;
#. ``self-management`` keeps ``command_run_visible: false`` and
   ``command_run_allowed: false``;
#. capability composition declares command network authority as profile-sensitive rather
   than universally unavailable;
#. capability composition encodes loopback-default/non-loopback-explicit exposure;
#. capability composition still denies raw credentials, credential helpers, devices,
   local control sockets, raw packet authority, and network-admin authority.

10.2 Fixture case lookup and content validation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The validator must not treat fixture case IDs as sufficient evidence. A required case
with the right ID but the wrong ``profile``, ``kind``, or ``expect`` values must fail
validation.

Use small pure helpers rather than a generic fixture framework. Preferred signatures:

.. code-block:: python

   def _mapping(value: Any, *, context: str) -> dict[str, Any] | None:
       ...

   def _fixture_cases_by_id(document: Any, *, context: str) -> dict[str, dict[str, Any]]:
       ...

   def _require_fixture_case(
       cases: dict[str, dict[str, Any]],
       case_id: str,
       *,
       kind: str | None = None,
       profile: str | None = None,
       expected: Mapping[str, Any] | None = None,
   ) -> None:
       ...

   def _profile_network_policy(
       policy: dict[str, Any],
       profile_id: str,
   ) -> dict[str, Any] | None:
       ...

``_fixture_cases_by_id`` must reject malformed/duplicate IDs rather than silently
letting the last item win.

``_require_fixture_case`` must:

* verify that the case exists;
* compare ``kind`` when supplied;
* compare ``profile`` when supplied;
* require an ``expect`` mapping when ``expected`` is supplied;
* compare every required expected authority field and fail if a field is missing or has
  the wrong value;
* ignore unrelated extra expectation fields so the validator remains focused on
  Bootstrap invariants.

If profile inheritance must be interpreted, support only the simple single-parent shape
already used by ``workspace-check-v1``. Do not build a runtime policy resolver in Phase
0.

10.3 Required command-isolation fixture assertions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The validator must assert semantic content for at least these cases:

``development-ipv4-application-network``
   Correct development profile/kind and ``ipv4: allowed``.

``development-ipv6-application-network``
   Correct development profile/kind and ``ipv6: allowed``.

``development-dns-resolution``
   Correct development profile/kind and ``dns: allowed``.

``development-loopback-listener-allowed``
   Correct development profile/kind and ``loopback_listener: allowed``.

``development-non-loopback-listener-requires-explicit-exposure``
   Correct development profile/kind and expectation equivalent to
   ``non_loopback_listener: explicit`` plus ``explicit_exposure_required: true``.

``default-profile-network-denied``
   Correct default/non-development profile or explicit profile absence and expectations
   showing application networking denied.

``development-unix-control-socket-denied``
   ``unix_sockets: denied``.

``development-inherited-socket-denied``
   ``inherited_sockets: denied``.

``development-raw-packet-denied``
   raw packet and network-admin authority denied.

``development-credential-agent-denied``
   raw credentials/helpers/inherited-agent authority denied.

The profile-consistency case must additionally assert the combined effective authority
set: allowed IPv4/IPv6/DNS and loopback listener; explicit non-loopback exposure; denied
control/inherited/raw/credential/device authority.

10.4 Required capability-composition fixture assertions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The validator must assert semantic content for at least:

* ``command-default-profile-network-deny``;
* ``development-command-application-network-allowed``;
* ``development-loopback-listener-default``;
* ``development-non-loopback-listener-needs-explicit-exposure``;
* ``development-network-does-not-grant-credential-broker``;
* ``development-network-does-not-grant-protected-data``.

For these cases it must compare their relevant ``kind``, ``profile`` where present, and
``expect`` fields so a changed expectation cannot pass merely because the ID remains.

10.5 Self-hosting scope validator
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

10.6 ``main`` integration
~~~~~~~~~~~~~~~~~~~~~~~~~

Call both new validators from ``main()`` after YAML/JSON parse validation and before the
final error report:

.. code-block:: python

   validate_bootstrap_command_profile_alignment()
   validate_bootstrap_self_hosting_scope_alignment()

The existing validator remains a deterministic repository check. Do not add network
access, subprocess-based runtime probing, or environment-dependent behaviour.

11. Versioning rules
--------------------

The Phase 0 implementation should use semantic contract/policy version bumps because
behavioural meaning changes.

Expected bumps:

* ``docs/security/command-execution.md``: ``1.1.0`` -> ``1.2.0``;
* ``docs/security/capability-composition.md``: ``1.1.0`` -> ``1.2.0``;
* ``spec/policy/command-profiles.yaml`` policy version: ``1.1.0`` -> ``1.2.0``;
* ``spec/policy/capability-zones.yaml`` policy version: ``1.1.0`` -> ``1.2.0``;
* related fixture policy version metadata: ``1.1.0`` -> ``1.2.0``.

Do not bump a serialization/schema version solely because policy values changed. If new
fields such as listener-bind semantics are not accepted by an existing schema, update
the smallest relevant schema/version as required and document that discovery in the
implementation PR.

12. Repository search audit
---------------------------

Before editing, run repository searches that cover both prose and machine-readable
sources. At minimum search for:

::

   command_run
   mediated_egress_only
   network_available
   ipv4: denied
   ipv6: denied
   dns: denied
   syscall_policy_required
   mandatory_access_control_required
   push
   package
   service restart
   self-update
   0.0.0.0
   loopback
   listener

Review every directly relevant hit. Record in the implementation PR description which
additional contradictory files, if any, were changed and why.

The search is an audit aid, not a license to rewrite historical or post-Bootstrap design
material that is not contradictory.

13. Dependency impact
---------------------

Phase 0 introduces **no runtime or development dependency**.

Do not create ``pyproject.toml`` or ``uv.lock`` in this phase. Existing repository
validation runs using the current scripts and their current CI dependencies.

If the existing validator already depends on PyYAML/jsonschema or other libraries, reuse
those dependencies. Do not add a policy or RST-processing framework merely for this
phase.

14. Implementation boundaries and interfaces
---------------------------------------------

Phase 0 contains no runtime application interfaces. The only new Python interfaces are
private validation helpers in ``scripts/validate_contracts.py``.

The planned helper signatures are intentionally narrow and may remain module-private:

.. code-block:: python

   def validate_bootstrap_command_profile_alignment() -> None: ...
   def validate_bootstrap_self_hosting_scope_alignment() -> None: ...
   def _fixture_cases_by_id(
       document: Any,
       *,
       context: str,
   ) -> dict[str, dict[str, Any]]: ...
   def _require_fixture_case(
       cases: dict[str, dict[str, Any]],
       case_id: str,
       *,
       kind: str | None = None,
       profile: str | None = None,
       expected: Mapping[str, Any] | None = None,
   ) -> None: ...

These are repository-validation implementation details and must not become application
ports, domain types, or a general policy library.

15. Security invariants
-----------------------

Credential invariant
~~~~~~~~~~~~~~~~~~~~

Normal application networking never makes reusable Binnacle, Git, SSH, GPG, or other
credentials model-visible or available to general development commands.

Control-plane invariant
~~~~~~~~~~~~~~~~~~~~~~~

Normal networking never grants the privileged-broker socket, executor control socket,
Binnacle protected IPC, inherited descriptors, or other protected local sockets.

Listener-exposure invariant
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Development servers bind to loopback by default. Non-loopback/LAN exposure requires an
explicit request/authority. Ordinary network permission alone is insufficient.

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

16. Test/fixture acceptance matrix
----------------------------------

.. list-table:: Phase 0 network and authority acceptance matrix
   :header-rows: 1
   :widths: 48 14 38

   * - Case
     - Expected
     - Contract
   * - Default command profile IPv4
     - denied
     - fail-closed default
   * - Development profile IPv4
     - allowed
     - Bootstrap development networking
   * - Development profile IPv6
     - allowed
     - Bootstrap development networking
   * - Development profile DNS
     - allowed
     - Bootstrap development networking
   * - Development loopback listener
     - allowed
     - local development-server default
   * - Development non-loopback/LAN listener without explicit exposure
     - denied/explicit-required
     - exposure is separate authority
   * - Development non-loopback/LAN listener with explicit exposure
     - allowed by explicit contract
     - deliberate development exposure
   * - Development profile protected Unix socket
     - denied
     - control-plane separation
   * - Inherited network/control socket
     - denied
     - descriptor separation
   * - Raw packet / network-admin capability
     - denied
     - privilege separation
   * - Raw credential material
     - denied
     - credential separation
   * - Inherited SSH/GPG credential agent
     - denied
     - credential separation
   * - Arbitrary device node
     - denied
     - hardware separation
   * - Self-management through ``command_run``
     - denied
     - dedicated privileged path
   * - Development process -> ordinary Internet/LAN API
     - allowed
     - normal software-development authority
   * - Development networking -> protected-data export
     - denied
     - capability-composition/information boundary
   * - Development networking -> credential broker
     - denied
     - outcome-oriented credential operation required

17. Local validation commands
-----------------------------

The implementation PR must run, at minimum:

::

   python scripts/validate_contracts.py
   python scripts/validate_schema_instances.py

If repository-local lint/documentation checks exist for reStructuredText or YAML, run
them as well. Do not add a new documentation framework solely to validate this phase.

The authoritative remote gate is the repository ``Contract validation`` GitHub Actions
workflow for the exact implementation commit.

18. Review checklist
--------------------

A reviewer should verify all of the following:

* global/default command networking is still fail-closed;
* authorised development profiles explicitly allow IPv4/IPv6/DNS application
  networking;
* loopback listener binding is the default for development servers;
* non-loopback/LAN listener exposure requires explicit authority;
* no raw credential/helper/agent authority leaks into general commands;
* no protected Unix/control sockets or inherited descriptors leak into commands;
* no raw packet/network-admin capability is granted;
* no arbitrary device authority is granted;
* ``self-management`` still cannot use ``command_run``;
* advanced syscall/MAC/namespace controls are no longer Bootstrap promotion blockers;
* mediated protected-data/credential-bearing egress semantics remain intact;
* fixture cases verify their semantic assertions, not only their IDs;
* self-hosting Git/package/service/restart exceptions remain narrow;
* no runtime implementation or Phase 1 work entered the change.

19. Deterministic acceptance checklist
--------------------------------------

Phase 0 implementation is accepted only when every item below is true:

#. required prose contracts describe the profile-sensitive network model;
#. required policy files encode default deny and explicit development-network authority;
#. loopback-default/non-loopback-explicit listener semantics are encoded;
#. fixture files contain positive development-network cases and permanent-boundary
   negative cases;
#. validator helpers check required fixture ``kind``, ``profile``, and relevant
   ``expect`` values;
#. malformed or duplicate fixture IDs fail validation;
#. a case with the correct ID but a wrong/missing expected authority fails validation;
#. current governing documents still declare the narrow signed-push/package/restart
   self-hosting requirements;
#. advanced sandbox hardening is clearly deferred without weakening the independent
   executor requirement;
#. contract and fixture version metadata are internally consistent;
#. repository search has no un-reconciled Bootstrap-blocking contradiction;
#. ``python scripts/validate_contracts.py`` passes;
#. ``python scripts/validate_schema_instances.py`` passes;
#. GitHub Actions ``Contract validation`` passes for the exact implementation head;
#. the implementation PR contains no Phase 1/runtime application work.

20. Failure and rollback guidance
---------------------------------

Because Phase 0 changes only contracts, policy declarations, fixtures, and validators,
rollback is a normal Git revert of the implementation commit.

Do not partially merge policy semantics. If the prose, machine-readable policy,
fixtures, and validator disagree, the Phase 0 exit gate has not passed.

If an existing consumer prevents an intended policy-shape change, preserve the governing
semantics using the smallest compatible representation and document the compatibility
constraint in the implementation PR. Do not silently retain the old behavioural
meaning merely to avoid a schema/version change.

21. Handoff to Phase 1
----------------------

Phase 1 detailed planning may begin only after this Phase 0 detailed plan has passed
review/CI and merged, as required by ``docs/implementation/index.rst``.

The actual Phase 0 implementation must then reconcile the contracts described here
before affected runtime capability is promoted. Phase 1 remains the executable project
skeleton phase and must not consume this plan as permission to implement later executor,
Git, or privileged functionality early.

Phase 0 intentionally establishes no runtime Python package or dependency. Its output is
a coherent, reviewable contract baseline that later implementation phases can trust.
