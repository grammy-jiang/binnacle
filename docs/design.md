# Binnacle Feature Design Specification V17

- **Document status:** Draft — scope-corrected server-only V1
- **Feature baseline candidate:** `BINNACLE-V1-SERVER-FEATURE-17-DRAFT`
- **Supersedes:** `design.v16.md` and the over-scoped `BINNACLE-PV1-FEATURE-14.1` baseline
- **Reason for supersession:** Owner-approved product-boundary correction: Binnacle V1 is a ChatGPT-facing MCP server and has no mandatory Companion, approval issuer, separate owner-facing application, or external control plane
- **Scope:** Technology-neutral feature design for the Binnacle MCP server repository
- **Strategic context:** ChatGPT operating a dedicated Raspberry Pi through MCP
- **Primary V1 owner:** A technically capable individual operating personally controlled Raspberry Pi devices through a private connection
- **V1 integration boundary:** Owner → ChatGPT → MCP → Binnacle → one Raspberry Pi
- **Supported-product status:** Not yet supported

## 1. Purpose

Binnacle is an independent MCP server installed on each Raspberry Pi to give ChatGPT a deterministic, policy-controlled interface for operating that device. Its purpose is to make ChatGPT capable of performing practical work on a Raspberry Pi across three core areas: host administration, software engineering, and hardware or peripheral development.

Through Binnacle, ChatGPT can inspect and manage the operating system, files, services, packages, networking, storage, source code, Git repositories, builds, tests, background processes, GPIO, I²C, SPI, UART, PWM, and connected peripherals such as cameras, touchscreens, storage devices, sensors, and network adapters.

Binnacle is not an AI agent. It does not interpret objectives, plan work, diagnose unfamiliar problems, select strategies, decide what is relevant to an objective, or coordinate other devices. ChatGPT remains the sole reasoning, planning, diagnostic, and multi-device coordination agent. Each Binnacle instance manages only its local Raspberry Pi.

Binnacle V1 works directly with ChatGPT through MCP. It does not depend on an Owner-control Companion, external approval issuer, separate owner-facing control application, or independent remote-control plane.

All Binnacle operations are subject to deterministic local controls, including controller authentication, local authorisation policy, privilege separation, resource limits, concurrency protection, information boundaries, auditing, safe failure handling, and recovery safeguards.

### 1.1 Normative language and product vocabulary

In this specification, **must** and **must not** identify requirements for every supported V1 workflow and device profile unless a narrower applicability statement is present. **Should** identifies recommended behaviour whose omission requires a recorded rationale and must not be relied upon by a V1 acceptance test. **May** identifies optional behaviour. Experimental and deferred capabilities are not V1 obligations until promoted explicitly.

The following terms have distinct scopes:

- **Owner:** the human who controls the Raspberry Pi, chooses its policy and uses ChatGPT as the reasoning surface.
- **Objective:** the owner outcome interpreted and pursued by ChatGPT; it is never interpreted by Binnacle.
- **Workflow:** a ChatGPT-coordinated sequence that achieves an owner goal and may contain several Binnacle operations.
- **Operation:** one bounded Binnacle request or retained unit of local work with one durable identity, operation contract, local authority scope and lifecycle.
- **Operation contract:** the versioned behavioural definition of an operation, including inputs, effects, policy class, preconditions, limits, evidence, retry, cancellation, failure and recovery semantics.
- **Prepared operation:** an optional, no-consequential-effect, server-derived representation of one exact normalised operation and its current deterministic preconditions. It may support owner presentation and state binding, but it is not human-approval proof and creates no authority by possession.
- **MCP task:** an optional MCP extension representation of one supported long-running request. It is not synonymous with every Binnacle operation and supplies no operation identity, authority or lifecycle semantics by itself.
- **Declared client metadata:** protocol-provided descriptive information about a client implementation. It is not authenticated controller identity.
- **Declared server metadata:** protocol-provided descriptive information about the Binnacle server implementation. It is not enrolled Raspberry Pi identity or proof of trust.
- **Authenticated controller identity:** the identity established from the verified transport or authorisation context of the ChatGPT MCP client and bound to a request.
- **Controller:** the ChatGPT host or application acting under the authenticated controller identity through its MCP client.
- **Interaction context:** the owner-facing ChatGPT conversation or application context. It is not an MCP protocol session and grants no Binnacle authority.
- **Correlation identity:** an opaque, non-authoritative label used only to associate evidence across operations, workflows or devices. It grants no authority and cannot change policy or lifecycle.
- **Local policy:** the owner-configured, device-local, deterministically enforceable rules that decide which controller operations are allowed and under what path, target, privilege, network, credential, hardware and resource bounds.
- **Device profile:** the owner-accepted definition of one Raspberry Pi's intended role, protected functions, supported capability classes, policy limits, recovery expectations and support tier.
- **Risk class:** the operation contract's deterministic classification of its maximum effect, such as observation, bounded modification, privileged change, destructive change, external side effect, hardware interaction or self-management.
- **Consequential boundary:** a contract-declared point immediately before a new external, persistent, privileged, destructive, physical, information-disclosure or otherwise material effect can begin or expand.
- **Operation owner:** the authenticated controller identity entitled to advance one controller-triggered operation lifecycle. A foundational protective rule may own only its predefined unattended protective action.
- **Supervision condition:** a machine-observable cancellation, deadline, lease, relinquishment, controller invalidation or watchdog condition whose state deterministically controls an operation; silence alone is not supervision loss.
- **Managed workload:** a persistent local process, service or scheduled action with its own stable identity, explicit durable authority and lifecycle, distinct from the operation that created it.
- **Foundational protective rule:** a versioned deterministic rule fixed by the Binnacle safety baseline or accepted device profile and limited to monitoring, evidence preservation, control-plane protection or one predefined safe-state effect.
- **Information class:** the device-profile and operation-contract treatment of one payload or derived fact: `never-disclosable`, `restricted-result` or `normal-result`.
- **Protected control plane:** Binnacle's own executable state, authentication material, policy, audit-integrity state, operation registry and recovery protections, which general-purpose operations must not modify directly.

An objective may contain workflows; a workflow may contain operations. Operations remain independently identifiable across MCP calls, retries, reconnections and changes to the ChatGPT interaction context.

### 1.2 Requirement ownership and repository boundary [GOV-OWN]

Normative obligations belong to three classes:

| Class | Accountable party | Repository and enforcement boundary |
| --- | --- | --- |
| **SERVER** | Binnacle MCP server | Implemented and tested by the Binnacle repository; directly enforceable on the Raspberry Pi. |
| **HOST** | ChatGPT host/application, reasoning model and MCP client | External to the Binnacle repository. Binnacle may validate assumptions and fail safely but cannot guarantee ChatGPT presentation, reasoning, confirmation or tool-selection behaviour. |
| **GOVERNANCE** | Owner | Supplies the device, local policy, trust configuration, physical safeguards, external credentials, intended role and acceptance decisions. Binnacle enforces only the local representation it can verify. |

The Binnacle repository owns:

- the MCP server;
- MCP discovery and operation contracts;
- local controller authentication integration;
- local policy enforcement;
- device observation and operation execution;
- durable operation lifecycle and evidence;
- control-plane isolation;
- local audit and recovery behaviour;
- the feature, security and compatibility tests for those responsibilities.

The Binnacle repository does not own:

- ChatGPT's user interface;
- ChatGPT's consent or confirmation mechanism;
- the reasoning model;
- a separate Companion application;
- a website or general-purpose human administration interface;
- fleet-wide coordination or shared reasoning state.

### 1.3 Normative precedence and traceability

When statements appear inconsistent, the following order governs:

1. canonical invariants;
2. defined vocabulary and requirement ownership;
3. a named contract with a stable identifier;
4. a narrower applicability rule;
5. a general requirement;
6. explanatory workflow prose.

A genuine conflict at the same or a higher level is a specification defect. The affected operation must fail closed and the conflict must return to product-design review rather than being resolved silently by implementation choice.

Stable cross-section contracts are:

| ID | Contract |
| --- | --- |
| `GOV-OWN` | Repository, HOST and owner responsibility boundary |
| `MCP-PROFILE` | Preferred and validated ChatGPT MCP interoperability profile |
| `MCP-INTERFACE` | MCP-facing capability, operation-contract and lifecycle interface |
| `TRUST-DEVICE` | Device identity and local trust lifecycle |
| `TRUST-CTRL` | Authenticated ChatGPT controller lifecycle |
| `LOCAL-POLICY` | Local policy hierarchy, operation classes and authoritative invocation decision |
| `OP-PREPARE` | Optional no-effect prepared-operation and exact-input binding contract |
| `OP-LIFECYCLE` | Durable operation identity, states, retry, cancellation and uncertainty |
| `OP-BOUNDARY` | Consequential-boundary declaration and revalidation |
| `INFO-BOUNDARY` | Information classification, result disclosure and secret protection |
| `CRED-DELEG` | Non-exportable credential use and raw-secret prohibition |
| `AUTO-FOUNDATION` | Foundational monitoring and protective automation |
| `SELF-MANAGE` | Controlled Binnacle self-development, update and restart |
| `RELEASE-GATE` | V1 workflow, compatibility, security and acceptance boundary |

### 1.4 Scope correction from V16

V17 is an owner-approved product-boundary correction, not an editorial revision.

The following V16 content is retained where directly applicable:

- Binnacle's purpose and three functional domains;
- ChatGPT as the sole reasoning agent;
- deterministic device-local behaviour;
- one instance per Raspberry Pi;
- local policy, least authority and safety;
- controlled general-purpose capabilities;
- durable operation lifecycle;
- concurrency, evidence, audit and recovery;
- MCP compatibility validation;
- self-management and staged expansion.

The following V16 concepts are removed from V1:

- `COMPANION` as a mandatory actor;
- Owner-control Companion;
- approval issuer;
- external authority grants and envelope grants;
- transition authority and transition proofs;
- issuer, transition-authority and grant epochs;
- the non-MCP device-side Companion endpoint;
- independent remote owner-control and recovery promises;
- `COMP-FEAS`, `COMP-VAL` and Companion-specific acceptance gates;
- a system-wide PX programme covering external applications.

They are replaced by:

- one authenticated ChatGPT controller;
- owner-configured local policy;
- host-side owner consent and confirmation, which Binnacle does not independently attest;
- deterministic operation preparation where useful;
- the MCP interface as Binnacle's only normal remote interface;
- local or physical recovery when ChatGPT or the network is unavailable.

## 2. Product Definition

Binnacle is the device-side execution and observation boundary between ChatGPT and one Raspberry Pi.

```text
Owner
  ↓ goals, confirmation and risk decisions
ChatGPT host/application
  ├─ reasoning model — interpretation, planning, diagnosis and coordination
  └─ MCP client — discovery, invocation and result routing
       ↓ authenticated MCP requests
Binnacle MCP server
  ├─ deterministic operation contracts
  ├─ local policy and safety enforcement
  ├─ durable operation lifecycle and evidence
  └─ controlled access to the local device
       ↓
Raspberry Pi OS, files, processes, services, hardware and peripherals
```

The host may ask the owner to confirm an action before invoking Binnacle. That confirmation is a HOST responsibility. V1 does not claim that Binnacle can independently prove that a particular ChatGPT confirmation occurred.

Binnacle's authoritative decision is narrower and local:

> Is this explicit request from the authenticated ChatGPT controller permitted by the current device profile, local policy, operation contract and verified device state?

Each Raspberry Pi runs an independent Binnacle instance. An instance:

- manages only its local device;
- has no peer-discovery or peer-communication feature;
- does not maintain a fleet view;
- contains no local model or agent;
- accepts requests only from configured authenticated controller identities;
- exposes only the capabilities permitted by the device profile;
- treats current local state as operational truth.

### 2.1 Interaction boundary

Binnacle V1 has one normal remote interaction surface: MCP.

| Surface | V1 role | Product boundary |
| --- | --- | --- |
| ChatGPT owner interaction | Goals, explanations, confirmation, progress and result presentation | External HOST behaviour; Binnacle supplies structured facts but does not control the UI. |
| MCP client-server relationship | Capability discovery, operation invocation, status, cancellation and results | The Binnacle repository's supported remote integration boundary. |
| Local or physical administration | Initial installation, trust setup, policy changes and break-glass recovery | Owner governance outside normal MCP operation. V1 does not promise remote availability when ChatGPT or the network is unavailable. |
| Traditional Binnacle website or dashboard | None | Excluded from V1. |

### 2.2 V1 delivery boundary

| Component | In the Binnacle repository? | V1 obligation |
| --- | ---: | --- |
| Binnacle MCP server | Yes | Deliver the server, operation contracts, local policy, lifecycle, evidence and tests. |
| ChatGPT host/application and MCP client | No | Must pass the validated interoperability profile before support is claimed. |
| Raspberry Pi OS and peripherals | No | Must be represented through validated device profiles and observed state. |
| Owner policy and physical safeguards | No | Supplied by the owner; Binnacle enforces the accepted local configuration. |
| Owner-control Companion or external approval service | No | Not part of Binnacle V1 and not a V1 dependency. |

### 2.3 Self-hosting development strategy

V1 must be useful enough for ChatGPT to help develop later Binnacle versions through Binnacle itself.

The initial server must therefore support a safe bootstrap development loop:

1. ChatGPT inspects the Binnacle repository and device state through MCP.
2. ChatGPT edits repository files through bounded file operations.
3. ChatGPT runs formatting, linting, tests and build commands through bounded command execution.
4. ChatGPT inspects diffs, logs and service state.
5. ChatGPT stages a controlled Binnacle restart or update.
6. Binnacle verifies restart outcome and reports failure or uncertainty honestly.
7. ChatGPT uses the resulting server to implement and validate the next capability set.

This is self-hosted development, not Binnacle autonomy. Binnacle never decides to modify or improve itself; ChatGPT requests each operation.

## 3. Core Design Principles

### 3.1 ChatGPT is the sole reasoning agent

ChatGPT is responsible for understanding owner intent, creating and adapting plans, diagnosing unfamiliar failures, assessing contextual risk, assessing whether a workflow appears complete, and coordinating multiple devices.

Binnacle must not perform semantic interpretation, open-ended diagnosis, objective relevance assessment or strategy selection.

### 3.2 Binnacle is deterministic

Every Binnacle action must be determined by:

- the selected operation contract;
- explicit request inputs;
- the authenticated controller;
- current local policy and device profile;
- verified local state;
- predefined limits, state transitions and failure rules.

When the next step requires judgement rather than deterministic evaluation, Binnacle must reject, stop at a declared boundary or return structured evidence to ChatGPT.

### 3.3 One instance controls one device

A Binnacle instance manages only its local Raspberry Pi. It may initiate a locally authorised remote side effect, but it does not own the remote system's authoritative state, concurrency, recovery or outcome guarantees.

### 3.4 Local policy is the server authority

V1 server authorisation comes from the authenticated controller plus local policy. A ChatGPT message, model statement, conversation identifier or host confirmation does not expand Binnacle authority.

An operation not permitted by local policy is rejected even when ChatGPT says the owner approved it. An operation permitted by local policy may be invoked after whatever HOST confirmation ChatGPT chooses to obtain.

### 3.5 Least authority applies throughout

File access, command execution, privileges, credentials, network destinations, processes, hardware interfaces and resource use must be limited to the operation contract and current policy.

If an authority dimension cannot be technically confined, the operation contract must truthfully declare the broader effective authority or the capability must remain unsupported.

### 3.6 Safety and recoverability take priority

Task completion and Binnacle availability are subordinate to:

- physical safety;
- integrity of the protected control plane;
- the Raspberry Pi's declared essential role;
- recoverability;
- honest representation of uncertain state.

### 3.7 Actual device state is operational truth

Stored facts, old observations and ChatGPT assumptions never override fresh verified state. Consequential operations must use observations that meet the contract's freshness requirement.

### 3.8 Owner control remains outside server reasoning

The owner is the final human decision-maker. ChatGPT provides the owner-facing reasoning surface. Binnacle enforces only the local policy and explicit operations it can verify.

### 3.9 Interface-first evolution

New functionality must first receive:

- a named owner outcome;
- an operation contract;
- a device-profile applicability rule;
- risk and information classifications;
- lifecycle, failure and recovery semantics;
- MCP interface behaviour;
- acceptance evidence.

Capability count is not itself a success measure.

## 4. Goals

Binnacle V1 is intended to achieve the following outcomes:

1. ChatGPT can connect to one Raspberry Pi and obtain trustworthy, structured device facts.
2. ChatGPT can perform practical software-engineering work on an authorised workspace without direct shell access by the owner.
3. ChatGPT can inspect and manage the Binnacle service sufficiently to support self-hosted development of later versions.
4. Every accepted operation reaches a verified result or a declared, recoverable and honestly reported non-success state.
5. Unauthorised, ambiguous, stale or unsupported work produces no unapproved consequential effect.
6. General-purpose commands remain isolated from Binnacle's control plane and respect their declared effective authority.
7. Credentials and non-disclosable data do not enter model-visible results, command output, ordinary logs or child-process state.
8. ChatGPT can coordinate multiple independently connected Binnacle instances without any Binnacle-to-Binnacle communication.
9. V1 provides a stable MCP interface baseline from which host administration and hardware support can expand incrementally.

## 5. Non-Goals

The following are outside Binnacle V1:

- a local AI model or local agent;
- planning, reasoning, autonomous diagnosis or objective pursuit by Binnacle;
- an Owner-control Companion, approval issuer or external authority-grant service;
- a separate remote emergency-control application;
- a traditional Binnacle website or dashboard;
- server-verifiable proof of a ChatGPT human-confirmation event;
- multi-agent orchestration;
- direct communication between Binnacle instances;
- fleet discovery or fleet-wide state ownership;
- multi-user or delegated-human administration;
- public unauthenticated exposure;
- owner-configurable unattended general automation;
- semantic interpretation of MCP operations as agent tasks;
- MCP Sampling or equivalent server-initiated model generation;
- safety-critical remote actuation;
- assuming every capability named in this document is supported in the initial V1 release;
- automatically changing Binnacle policy through ordinary MCP operations;
- guaranteeing remote recovery after device power loss, network loss or highest-privilege compromise.

## 6. Responsibility Model

| Responsibility | Owner | ChatGPT host/application | Reasoning model | MCP client | Binnacle |
| --- | ---: | ---: | ---: | ---: | ---: |
| Define goals and acceptable risk | Final authority | Presents and records | Assists | No | No |
| Obtain human consent or confirmation | Decides | Owns interaction | May explain | May carry result | Cannot independently attest |
| Interpret natural-language intent | Supplies intent | Provides context | Yes | No | No |
| Plan, diagnose and coordinate devices | Governs | Maintains context | Yes | Routes | No |
| Authenticate the remote controller | Configures trust | Presents credentials/context | No | Carries verified context | Verifies |
| Discover and select operations | No | Controls exposure and refresh | Proposes | Discovers and invokes | Advertises advisory catalogue |
| Define local authority | Configures device profile and policy | Cannot expand | Cannot expand | Cannot expand | Enforces |
| Validate explicit inputs and current state | No | Supplies explicit inputs | May propose | Preserves request identity | Yes |
| Execute and track local operations | No | Supervises | Requests through host | Correlates calls | Yes |
| Decide broader workflow completion | Final authority | Presents evidence | Assesses | No | Reports local outcome only |
| Maintain authoritative local operation state | No | No | No | No | Yes |
| Maintain local audit history | Governs retention | May display/export authorised records | No | Preserves correlation | Yes |
| Coordinate multiple Raspberry Pis | Governs | Maintains connections | Yes | One relationship per server | No |

## 7. Operating and Authorisation Model

### 7.1 Controller authentication [TRUST-CTRL]

Every normal MCP request must be associated with an authenticated controller identity established through the selected transport or authorisation profile.

Protocol-declared client metadata is descriptive only and must not be accepted as controller authentication.

V1 should support one locally active ChatGPT controller identity per Binnacle instance. Replacing the controller must invalidate the old controller's ability to create new requests. Existing operation handling follows the operation contract and local policy; no operation ownership transfers automatically.

### 7.2 Local policy hierarchy [LOCAL-POLICY]

The most restrictive applicable rule governs:

1. non-bypassable Binnacle safety and control-plane protections;
2. the device profile's maximum operating envelope;
3. controller-specific permissions;
4. the operation contract's maximum effects;
5. explicit request parameters and current local state.

V1 does not use remote authority grants. Local policy must decide whether each operation is:

- allowed within declared bounds;
- denied;
- unavailable on the current profile;
- temporarily unavailable because of state, resource or trust conditions.

Local policy changes are owner-governed configuration changes and are not ordinary MCP operations in V1.

### 7.3 Operation risk classes

Every operation contract declares one or more maximum-effect classes:

| Class | Typical effect | V1 policy treatment |
| --- | --- | --- |
| **Observation** | Read current state without intentional modification | May be broadly enabled within declared information and resource bounds. |
| **Bounded modification** | Modify authorised workspace or non-critical service state | Enabled only for named paths, services and targets. |
| **Privileged/system** | Requires elevated OS privilege or affects shared system state | Disabled by default or restricted to dedicated outcome-oriented tools. |
| **Destructive** | Deletes data, replaces state or creates difficult recovery | Requires explicit local enablement and strong scope constraints; otherwise unsupported. |
| **External side effect** | Contacts or modifies a remote service | Requires explicit destinations, actions, data direction and volume. |
| **Hardware interaction** | Reads or drives GPIO, buses or peripherals | Requires a validated hardware profile, reservations and safe-state contract. |
| **Self-management** | Changes Binnacle code, dependencies, configuration or service state | Requires the `SELF-MANAGE` contract and staged verification. |

Risk classification is deterministic and contract-defined. Binnacle does not raise or lower risk by semantic judgement.

### 7.4 Host confirmation boundary

ChatGPT may ask the owner to confirm operations according to its own product behaviour and risk judgement.

Binnacle V1 must not claim that:

- a ChatGPT confirmation is cryptographically proven to the server;
- a conversation message constitutes owner authority;
- a model statement can override local policy.

Consequential operations that cannot be safely authorised through static local policy and explicit bounds must remain disabled in V1 rather than depending on unverifiable human confirmation.

### 7.5 Prepared operations [OP-PREPARE]

Selected consequential operations may support a deterministic prepare/execute pattern.

Preparation:

- has no consequential effect;
- normalises exact targets and material parameters;
- reports current preconditions and relevant device state;
- reports the operation contract, maximum effects, policy class and recovery semantics;
- may allocate a short-lived prepared-operation identity;
- creates no authority and is safe to discard.

Execution:

- must still pass controller authentication and local policy;
- must match the prepared operation where the contract requires exact binding;
- must revalidate current state before every consequential boundary;
- rejects material mismatch or expiry.

A prepared-operation identity is a state-binding mechanism, not proof of owner approval.

### 7.6 ChatGPT autonomy is not a Binnacle mode

The owner may allow ChatGPT to make several MCP calls without asking for confirmation after every step. That is a HOST and owner interaction choice.

Binnacle has no semantic autonomous mode. It evaluates every invocation independently under the same local policy and operation contracts.

### 7.7 Policy and profile changes

Every accepted operation remains associated with the policy, device-profile and operation-contract versions under which it was admitted.

When a relevant policy or profile changes:

- pending work is revalidated;
- work that no longer qualifies must pause, stop, fail or enter uncertainty according to its contract;
- historical evidence is not rewritten;
- a more permissive change does not automatically resume old work.

### 7.8 Plan transparency belongs to ChatGPT

For consequential work, ChatGPT should present:

- the objective;
- planned operations;
- expected effects;
- risk boundaries;
- recovery approach;
- completion criteria.

Binnacle supplies deterministic operation facts and does not judge the plan semantically.

## 8. Device Identity, Trust and Profiles

### 8.1 Stable device identity [TRUST-DEVICE]

Every Binnacle instance must expose a stable owner-recognised device identity distinct from its human-readable name and declared server metadata.

The identity is used for:

- connection recognition;
- operation evidence;
- policy binding;
- cross-device correlation by ChatGPT;
- rebuild and re-enrolment decisions.

### 8.2 V1 bootstrap and trust setup

Initial installation and trust establishment occur through local owner administration outside normal MCP operation.

The bootstrap process must establish:

- the Binnacle device identity;
- the accepted device profile;
- the authenticated ChatGPT controller configuration;
- local policy;
- protected control-plane paths;
- recovery instructions;
- the initial audit state.

Binnacle must not self-assert successful recovery after highest-privilege compromise. A materially rebuilt or compromised device requires local reassessment and explicit reconfiguration before normal remote operation resumes.

### 8.3 Controller lifecycle [TRUST-CTRL]

V1 supports:

- one active controller identity;
- local suspension or removal;
- explicit replacement;
- rejection of old controller material after replacement;
- owner-visible evidence of the currently configured controller identity.

A ChatGPT conversation is not a controller identity. Different conversations under the same authenticated ChatGPT controller are not isolated security principals.

### 8.4 Device profiles

Every supported profile defines:

- intended device role and protected functions;
- operating-system and hardware assumptions;
- supported operation contracts;
- allowed paths and workspaces;
- allowed services and processes;
- privilege limits;
- destructive-operation limits;
- external network targets;
- credential delegations;
- resource ceilings;
- hardware reservations and safe states;
- control-plane protection;
- recovery expectations;
- support tier.

### 8.5 Support tiers

| Tier | Meaning |
| --- | --- |
| **Supported** | The exact profile and exposed operation set pass the V1 release gates. |
| **Restricted** | Observation or recovery only; normal modification is disabled. |
| **Experimental** | Private learning profile with explicit limitations and no supported-use claim. |
| **Unsupported** | Binnacle makes no operational guarantee and must not expose consequential operations. |

### 8.6 Trusted time and ordering

Binnacle must distinguish:

- wall-clock timestamps;
- monotonic elapsed time within one boot;
- durable local ordering across restart.

Clock rollback, reboot or loss of trusted wall time must not extend operation deadlines, freshness or retention guarantees.

### 8.7 Threat boundary

Binnacle must protect against:

- unauthorised MCP access;
- malformed or replayed requests;
- stale or misleading device state;
- untrusted file, repository, package and command content;
- privilege escalation;
- filesystem, process, network and hardware escape;
- credential leakage;
- resource exhaustion;
- audit tampering;
- accidental self-destruction of the control plane.

If the Raspberry Pi is compromised at the highest local privilege boundary, the Binnacle instance is not trustworthy. It must be isolated and rebuilt rather than relied upon to prove its own recovery.

## 9. MCP-Facing Capability Design

### 9.1 Outcome-oriented capabilities

Common operations should be exposed as bounded, outcome-oriented MCP operations with:

- clear inputs;
- deterministic validation;
- explicit maximum effects;
- structured evidence;
- known failure and recovery semantics.

Outcome-oriented operations are preferred over unrestricted command execution when they can express the owner goal without losing necessary capability.

### 9.2 Controlled general-purpose capabilities

General-purpose file, command and device access remains necessary for software engineering, diagnosis and future hardware development.

General-purpose operations must:

- run under their declared effective authority;
- remain isolated from the protected control plane;
- respect path, network, privilege, credential, process and resource limits;
- apply those limits to every descendant and helper;
- report when a dimension cannot be confined;
- never silently receive Binnacle's own privilege or secrets.

### 9.3 MCP primitive ownership

V1 uses MCP primitives according to their control model:

- **Tools:** model-invoked observations and side-effecting operations;
- **Resources:** optional factual records or content selected by the HOST for context;
- **Prompts:** optional explicit reusable templates only where a product need exists;
- **Tasks:** optional representation of supported long-running requests when both sides support the extension;
- **Sampling:** not used.

Resources and prompts are not mandatory. No primitive bypasses local policy.

### 9.4 Discovery and catalogue behaviour

The visible operation catalogue should reflect:

- the device profile;
- platform support tier;
- operation-contract versions;
- current broad availability and restrictions.

Discovery is advisory. The MCP host may cache tool metadata. Every invocation must therefore perform authoritative authentication, policy and current-state validation.

Catalogue entries must have stable semantic identities and explicit versions. Changes to inputs, effects, policy class, evidence, cancellation or failure semantics are behavioural changes.

### 9.5 Operation contract requirements [MCP-INTERFACE]

Every exposed operation must define:

- semantic identity and version;
- purpose and non-purpose;
- input schema and normalisation;
- maximum effects and risk classes;
- local policy requirements;
- preconditions and freshness;
- idempotency and duplicate semantics;
- timeout and resource limits;
- operation identity and lifecycle;
- cancellation behaviour;
- result and error schema;
- evidence and provenance;
- information classes;
- device-profile applicability;
- recovery and uncertainty behaviour.

### 9.6 Long-running work and MCP Tasks

Binnacle's durable operation identity and lifecycle remain authoritative whether or not MCP Tasks is used.

A validated profile must state:

- which operations may become long-running;
- how the HOST obtains status;
- whether MCP Tasks is supported;
- how task identifiers map to Binnacle operation identities;
- how cancellation acknowledgement differs from verified local cancellation;
- how results are retained after disconnect;
- how retry reconciles the same operation.

### 9.7 Result and error model

The interface must distinguish:

- MCP protocol or transport error;
- unsupported operation or profile;
- authentication failure;
- policy rejection;
- invalid input;
- stale or conflicting state;
- resource or concurrency rejection;
- execution failure with known effects;
- cancellation requested;
- cancellation verified;
- uncertain effect or outcome;
- successful local verification.

A transport success must not be interpreted as operation success.

### 9.8 Untrusted-content and composition boundary

Repositories, files, packages, command output, tool metadata, peripheral input and external responses are untrusted data.

Content cannot:

- expand local policy;
- select another Binnacle operation;
- change an operation contract;
- alter its own information class;
- create network or credential authority;
- direct Binnacle to treat instructions as owner intent.

Combining protected-data access with outbound transfer or another consequential capability requires an explicit operation contract and policy rule naming the data, destination and maximum effect.

### 9.9 Separate MCP Interface Design deliverable

After `MCP-FEAS`, the repository must create a separate **Binnacle MCP Interface Design** that freezes:

- the actual ChatGPT-compatible MCP profile;
- operation groups and granularity;
- individual tool and resource contracts;
- discovery, versioning and deprecation;
- operation-state and evidence schemas;
- error taxonomy;
- Tasks and cancellation projection;
- result-size and retention behaviour;
- compatibility test cases.

That document is an interface specification, not a website or Companion UI design.

## 10. Functional Domains and V1 Scope

### 10.1 Product-direction domains

Binnacle's repository purpose covers:

1. host administration;
2. software engineering;
3. hardware and peripheral development.

These catalogues define product direction, not automatic V1 support.

### 10.2 Host administration direction

Potential bounded capabilities include:

- OS and device information;
- service and process inspection;
- service restart and bounded recovery;
- package and update inspection;
- authorised package changes;
- network inspection;
- storage and filesystem status;
- logs and health evidence;
- reboot and maintenance operations;
- users and permissions through dedicated contracts.

### 10.3 Software engineering direction

Potential capabilities include:

- file and directory operations;
- repository inspection;
- exact patch and file modification;
- Git status, diff, branch and commit operations;
- command execution;
- dependency and environment management;
- formatting, linting, builds and tests;
- debugging and log inspection;
- controlled development services;
- artefact transfer under explicit network and information policy.

### 10.4 Hardware and peripheral direction

Potential capabilities include:

- GPIO;
- I²C;
- SPI;
- UART;
- PWM;
- cameras and displays;
- USB and network adapters;
- sensors and controllers.

Consequential hardware control is not required for the initial V1 supported baseline. It is added only after a hardware profile and safety acceptance exist.

### 10.5 Initial V1 supported workflows

The initial V1 is deliberately self-hosting capable rather than feature-complete.

| ID | Owner job | Minimum Binnacle capability | Verified success | Protected non-success |
| --- | --- | --- | --- | --- |
| **B1 — Connect and inspect** | Connect ChatGPT to one configured Raspberry Pi and understand its current state | Authentication, discovery, device identity, profile, filesystem and service observation | ChatGPT receives current structured facts from the intended device | No modification occurs; reason and recovery action are reported |
| **S1 — Modify and verify the Binnacle workspace** | Ask ChatGPT to make a bounded repository change | Read/search files, exact edits, bounded workspace command execution, Git diff, formatting/lint/test | Requested change exists and declared verification passes | Partial files/processes are identified or cleaned; unrelated paths remain untouched |
| **H1 — Inspect and restart the Binnacle service** | Diagnose a non-critical Binnacle service failure and restore it | Service state, logs, process status, controlled restart, post-restart verification | Service reaches declared healthy state and reconnects | Service remains stopped or restricted; logs and next local recovery step are reported |
| **R1 — Recover from failed or uncertain work** | Understand and contain an operation failure, cancellation or uncertain outcome | Durable operation status, cancellation, evidence, cleanup and restricted state | The operation reaches a verified terminal state or an explicit owner-intervention state | No automatic duplicate effect; last verified facts remain available |

### 10.6 Initial V1 capability minimum

To support those workflows, V1 must provide at least:

- server identity and capability discovery;
- local controller authentication;
- device and profile inspection;
- bounded filesystem listing, reading, searching, writing and patching;
- bounded command execution;
- process and service inspection;
- Binnacle service logs and controlled restart;
- Git status and diff inspection;
- formatting, linting, test and build execution;
- durable operation identity and status;
- cancellation and uncertain-outcome reporting;
- local audit and structured evidence;
- control-plane protection.

The exact MCP operations are defined later in `MCP-INTERFACE`.

### 10.7 Post-V1 expansion

After V1 is connected to ChatGPT, ChatGPT may use Binnacle to implement and validate:

- richer host administration tools;
- package and update management;
- external repository and CI integration;
- managed development services;
- hardware observation;
- bounded hardware actuation;
- additional Raspberry Pi profiles;
- improved recovery and self-update behaviour.

Every expansion follows the same feature, interface, security and acceptance process. Binnacle itself never initiates expansion.

## 11. Deterministic Operation Lifecycle [OP-LIFECYCLE]

### 11.1 Admission and validation

Before starting an operation, Binnacle must validate:

- operation identity and contract version;
- authenticated controller;
- device identity, profile and trust state;
- explicit inputs and normalisation;
- local policy;
- target existence and current state;
- information and network scope;
- privilege and credential requirements;
- resource and concurrency availability;
- recovery and evidence prerequisites.

Validation determines only whether the explicit operation is permitted. It does not determine whether it is strategically appropriate for the owner's objective.

### 11.2 Lifecycle states

An operation uses explicit states:

| State | Meaning |
| --- | --- |
| `received` | The operation identity exists; no effect is implied. |
| `rejected` | Validation failed and no consequential effect began. |
| `authorised` | Local validation passed, but no consequential boundary has been crossed. |
| `running` | The operation is executing. |
| `paused` | Progress is intentionally stopped at a declared safe boundary. |
| `cancelling` | A cancellation request is being applied. |
| `cancelled` | The declared cancellation result and remaining effects are verified. |
| `succeeded` | The local success condition is verified. |
| `failed` | A known non-success result with known remaining effects is verified. |
| `uncertain` | The effect or outcome cannot be established safely; success and automatic repetition are prohibited. |

Only Binnacle advances authoritative local operation state.

### 11.3 Consequential-boundary revalidation [OP-BOUNDARY]

Immediately before each declared consequential boundary, Binnacle revalidates the applicable:

- controller and device trust;
- local policy and profile;
- state and freshness predicates;
- target, path and external endpoint;
- privilege and credential delegation;
- resource reservation;
- hardware interlock or measurement;
- cancellation and supervision state;
- recovery prerequisite.

A failed revalidation blocks that later effect and produces the operation contract's declared state transition.

### 11.4 Retry and duplicate semantics

Each operation contract declares whether it is:

- read-only and safely repeatable;
- idempotent under one operation identity;
- non-idempotent and never automatically repeatable;
- externally uncertain and requiring reconciliation.

A retry with the same operation identity reconciles the retained lifecycle. A new operation identity is not permitted to repeat an uncertain prior effect merely because the transport retried.

### 11.5 Cancellation

Cancellation is cooperative and contract-specific.

A cancellation request may result in:

- immediate stop before effect;
- stop at the next safe boundary;
- predefined rollback;
- safe-state transition;
- preserve-and-block;
- inability to stop, with the operation remaining `running` or `uncertain`.

An MCP cancellation acknowledgement is not a verified Binnacle `cancelled` state.

### 11.6 Long-running operations

Long-running work must remain queryable after the initiating MCP call ends where the operation contract promises retention.

Binnacle must define:

- retention period;
- status and result retrieval;
- supervision conditions;
- reconnect behaviour;
- cancellation semantics;
- resource ownership;
- cleanup and expiry.

Absence of a new ChatGPT request has no lifecycle meaning by itself.

### 11.7 Completion

Binnacle verifies only the local operation outcome and returns evidence. ChatGPT assesses whether the broader workflow appears complete, and the owner remains the final human decision-maker.

### 11.8 Managed workloads

A process or service may outlive its creating operation only through explicit atomic transfer to a managed-workload identity and contract.

If managed workloads are not supported by the active profile, background processes created by an operation must be terminated or explicitly reported before operation closure.

## 12. Risk and Safety Controls

### 12.1 Deterministic risk classification

Risk classes are fixed by the operation contract and device profile. Binnacle may apply deterministic escalation conditions, but it does not perform contextual risk judgement.

### 12.2 Ambiguity

Semantic ambiguity never expands permission. Missing targets, paths, destinations, privilege bounds, hardware identities or other material inputs produce rejection or a request for explicit values.

### 12.3 Destructive operations

Delete, overwrite, format, reset and irreversible state replacement require:

- exact target identity;
- declared maximum scope;
- current-state revalidation;
- explicit local policy enablement;
- known recovery or truthful absence of recovery;
- result evidence.

Broad wildcard destruction is unsupported unless a future operation contract defines deterministic membership and protection.

### 12.4 Physical and hardware safety

Hardware operations require:

- validated peripheral identity;
- exclusive reservation where required;
- electrical, timing and duration limits;
- fresh interlock or sensor state where applicable;
- predefined safe state;
- physical-intervention instructions;
- explicit uncertainty handling.

Owner confirmation cannot replace a required physical interlock.

### 12.5 External software and artefacts

Package, repository or executable availability does not establish trust. Binnacle must expose source, provenance and integrity evidence where available and apply explicit local policy before installation or execution.

### 12.6 External systems

Authority over the Raspberry Pi does not imply authority over reachable external systems. Every external observation, modification or transfer must name:

- target;
- action;
- information class;
- direction;
- volume or maximum effect;
- uncertain-outcome behaviour.

### 12.7 Resource governance

The device profile defines limits for:

- CPU and execution time;
- memory;
- process count;
- storage and temporary data;
- network use;
- power and hardware duty;
- concurrent operations.

Binnacle must preserve capacity for its control plane, status, cancellation, audit completion and safe stop.

## 13. Credentials, Information and Network Boundaries

### 13.1 Credential delegation [CRED-DELEG]

Credential presence does not imply permission to use it.

V1 supports only non-exportable credential use where a protected component can perform an explicitly allowed target action without revealing the raw secret to ChatGPT, the invoking command or its descendants.

Raw secret material must not enter:

- model context;
- tool input or output;
- command arguments or environment;
- operation-accessible files or descriptors;
- child-process memory where avoidable;
- ordinary logs or audit payloads.

If a target protocol cannot support bounded non-exportable use, the credential-bearing operation is unsupported in V1.

### 13.2 Information classes [INFO-BOUNDARY]

| Class | Meaning |
| --- | --- |
| `never-disclosable` | Credentials, private keys, authentication material, protected control-plane secrets and raw policy secrets. They are never returned to ChatGPT. |
| `restricted-result` | Potentially sensitive device, file or command content returned only when the operation contract and local policy explicitly permit disclosure to ChatGPT. |
| `normal-result` | Routine operational facts permitted by the profile. |

Every result field and payload must have a prospective class. Errors, logs and audit must not become an alternative disclosure path.

### 13.3 Outbound network authority

Outbound operations require explicit effective destinations. DNS resolution, selected address, redirect, proxy and application-visible protocol transition must remain within policy.

Unexpected private, metadata, device-local or otherwise sensitive targets fail closed unless explicitly permitted.

### 13.4 Inbound exposure

Binnacle V1 is private-connectivity-first. Public inbound exposure is outside the default supported profile.

The active transport profile must define:

- authentication;
- encryption expectations;
- accepted source or network boundary;
- request-size and rate limits;
- connection failure behaviour.

## 14. Concurrency and Isolation

### 14.1 Controlled concurrency

Operations may run concurrently only when their contracts declare compatible resource use.

Binnacle must provide deterministic ownership or reservation for:

- files and workspaces where needed;
- services and package managers;
- network configuration;
- GPIO and hardware interfaces;
- Binnacle self-management;
- managed workloads.

### 14.2 General-purpose isolation

General-purpose execution must be isolated from:

- Binnacle authentication material;
- policy configuration;
- operation registry and audit integrity;
- recovery protections;
- Binnacle executable state except through `SELF-MANAGE`;
- unrelated operation contexts.

### 14.3 Conversation and controller boundary

Binnacle does not infer security isolation from ChatGPT conversations. All conversations using the same authenticated controller are one security principal.

Operation identity, explicit resource ownership and concurrency rules prevent accidental collision.

## 15. Evidence, Audit and Factual Device Records

### 15.1 Structured operation evidence

Every consequential operation must produce evidence containing, as applicable:

- device identity;
- operation identity and contract version;
- authenticated controller identity reference;
- profile and policy versions;
- normalised inputs and targets;
- initial observations and freshness;
- state transitions and timestamps/order;
- effects and external targets;
- resource reservations;
- verification result;
- cancellation, cleanup and remaining effects;
- uncertainty and recommended next observation.

### 15.2 Provenance and freshness

Reported information must distinguish:

- direct current observation;
- verified operation outcome;
- historical record;
- cached or potentially stale data;
- externally supplied information;
- conflicting or unverified state.

### 15.3 Audit

Binnacle owns the local audit of:

- authentication result;
- operation request and policy decision;
- operation lifecycle;
- local effects;
- external initiation;
- result and uncertainty;
- cleanup and recovery.

Binnacle does not claim authoritative knowledge of what ChatGPT showed the owner or whether the owner confirmed it.

### 15.4 Audit integrity and retention

The profile must define:

- retention period;
- maximum size;
- integrity checks;
- access policy;
- export behaviour;
- failure behaviour when protected audit storage is unavailable.

A failure to preserve required audit evidence must restrict affected consequential operations rather than silently continuing.

### 15.5 Persistent factual device record

Binnacle may maintain verified facts such as:

- hardware identity;
- OS and package versions;
- services;
- interface inventory;
- device-profile version;
- incidents and recovery results;
- capability support status.

Records must identify source and freshness and must not become inferred beliefs.

### 15.6 Actionable policy explanations

A rejection should identify:

- operation and target;
- failed policy or state condition;
- whether retry is meaningful;
- safe next observation or owner action;
- information withheld for security.

## 16. Monitoring and Foundational Automation

### 16.1 Monitoring

Profiles may enable deterministic monitoring of:

- Binnacle service health;
- resource ceilings;
- storage pressure;
- operation watchdogs;
- hardware safety values;
- audit integrity;
- protected-role availability.

### 16.2 Foundational protective automation [AUTO-FOUNDATION]

V1 unattended automation is limited to fixed protective behaviour such as:

- stop an operation on deadline or resource breach;
- preserve evidence;
- return a hardware output to a declared safe state;
- keep the Binnacle control plane available;
- place the server into restricted mode after integrity failure.

It must not:

- pursue an objective;
- perform routine maintenance;
- install updates;
- edit source code;
- create managed workloads;
- select a new recovery strategy.

### 16.3 Desired state

Broad desired-state correction is outside V1. A profile may define only narrowly bounded safe-state or control-plane protection that can be restored deterministically.

## 17. Recovery, Resilience and Self-Management

### 17.1 Predefined recovery

Every consequential operation declares one or more of:

- no-effect rejection;
- retry-safe reconciliation;
- stop at safe boundary;
- rollback;
- safe state;
- preserve-and-block;
- owner intervention;
- uncertain state requiring inspection.

### 17.2 ChatGPT or connection loss

If ChatGPT or the MCP connection is unavailable:

- Binnacle starts no new objective-driven work;
- an already-running operation may continue only while its declared supervision remains valid;
- after supervision loss, only the operation's predefined protective effect may occur;
- remote owner recovery is not guaranteed;
- local service management, network restoration, reboot or physical access may be required.

### 17.3 Restricted state

Binnacle enters restricted state when required trust, policy, audit, time, storage or control-plane integrity cannot be established.

Restricted state may expose only:

- bounded status;
- diagnostic observation;
- audit/evidence retrieval permitted by policy;
- safe shutdown or local recovery actions whose contracts remain valid.

### 17.4 Backup and restoration

Backup may preserve configuration, evidence and factual records, but restoration does not automatically restore trust. Rebuild and reconfiguration must re-establish device identity, controller trust and policy.

### 17.5 Controlled self-management [SELF-MANAGE]

Binnacle may be developed and maintained through Binnacle only under dedicated self-management operations.

A controlled self-update or restart must provide:

- exact source or artefact identity;
- current repository and service state;
- isolated build and test result;
- staged deployment boundary;
- control-plane file protections;
- restart command and timeout;
- health verification;
- rollback or local recovery instructions;
- evidence retained outside the replaced process where necessary.

General-purpose workspace commands do not automatically receive permission to alter Binnacle's installed executable, authentication, policy, audit or service configuration.

### 17.6 Highest-boundary compromise

When the Raspberry Pi or Binnacle's highest local privilege boundary is compromised, the server cannot prove its own trustworthiness or safe recovery.

The owner must use local or physical isolation, rebuild and reconfiguration. V1 makes no claim of independent remote recovery in that condition.

## 18. Multi-Device Behaviour

Each Binnacle instance is independent.

ChatGPT may:

- maintain several MCP connections;
- select the target device;
- sequence operations across devices;
- compare evidence;
- handle cross-device failure and compensation reasoning.

Binnacle must not:

- discover peers;
- call another Binnacle instance;
- share authority or credentials with peers;
- decide cross-device ordering;
- claim fleet-wide completion.

A cross-device correlation identity is evidence only and grants no local authority.

## 19. Capability and Product Lifecycle

### 19.1 Capability lifecycle

Each operation contract has one lifecycle state:

| State | Meaning |
| --- | --- |
| `experimental` | Private learning capability with explicit limitations and no supported-use claim. |
| `validated` | Behaviour and safety tested on named profiles but not yet broadly supported. |
| `supported` | Included in the supported V1 profile and release gates. |
| `restricted` | Observation or recovery only because a dependency or integrity condition failed. |
| `deprecated` | Still available temporarily with a declared replacement and removal plan. |
| `retired` | No longer exposed for new operations. |

Discovery metadata alone cannot promote capability state.

### 19.2 MCP interoperability profile [MCP-PROFILE]

The design target inherited from V16 is MCP 2026-07-28, but this is not a claim that the actual ChatGPT host supports it.

The validated ChatGPT profile must record:

- actual protocol revision;
- transport and authentication;
- discovery and cache behaviour;
- supported MCP primitives and extensions;
- tool-schema limits;
- result and error limits;
- long-running operation and Tasks behaviour;
- cancellation behaviour;
- MRTR or elicitation behaviour where applicable;
- model-visible field handling;
- explicit absence of Sampling;
- tested Binnacle workflows.

A legacy or dual-era profile may be accepted only after explicit compatibility testing. No behaviour is silently emulated.

### 19.3 Staged rollout

Recommended stages are:

1. **Disposable MCP feasibility server** — prove ChatGPT connection, authentication, discovery, invocation and result routing.
2. **Bootstrap Binnacle V1 preview** — implement B1, S1, H1 and R1 on one private device.
3. **Self-hosted development** — use Binnacle through ChatGPT to improve the repository and add validated operations.
4. **V1 supported baseline** — pass the full V1 release gates on the named device profile.
5. **Post-V1 expansion** — add host administration and hardware capability sets through new contracts and tests.

### 19.4 Governance review

Binnacle should deterministically identify:

- disabled or stale operation contracts;
- orphaned processes or ownership;
- missing required evidence;
- expired temporary data;
- policy inconsistencies;
- unsupported profile assumptions;
- unmanaged persistent workloads.

Ambiguous remediation returns to ChatGPT or the owner.

## 20. V1 Release Acceptance [RELEASE-GATE]

### 20.1 V1 acceptance governance

Before evaluation, freeze:

- the target ChatGPT product/account and MCP profile;
- the Raspberry Pi and device profile;
- the authenticated controller configuration;
- the operation contracts in scope;
- the B1, S1, H1 and R1 scenarios;
- security and resource budgets;
- evidence sources and pass/fail rules;
- manual baseline where useful.

### 20.2 Required V1 gates

| Gate | Pass condition |
| --- | --- |
| **Scope** | Only the named V1 operation set is supported; all others are labelled experimental, restricted or unsupported. |
| **MCP connectivity** | The actual ChatGPT host authenticates, discovers and invokes Binnacle through the validated profile. |
| **Determinism** | No Binnacle path performs semantic planning, diagnosis or objective adaptation. |
| **Controller authentication** | Unauthenticated, stale or replaced controller requests are rejected. |
| **Local policy** | Every operation is accepted or rejected according to the frozen device profile and policy; host prose cannot override it. |
| **Interface contracts** | Every exposed operation has a versioned `MCP-INTERFACE` contract and tested result/error behaviour. |
| **B1 workflow** | ChatGPT connects to the intended device and obtains fresh structured identity, profile and system evidence. |
| **S1 workflow** | ChatGPT modifies the authorised repository, runs declared verification and produces an exact diff without affecting unrelated paths. |
| **H1 workflow** | ChatGPT diagnoses and safely restarts the Binnacle service, or reaches a verified restricted/local-intervention state. |
| **R1 workflow** | Failure, cancellation, disconnect, restart and uncertainty cases preserve durable state and avoid duplicate effects. |
| **General-purpose confinement** | Commands and descendants remain inside their declared effective authority or the capability is unsupported. |
| **Control-plane isolation** | Workspace and command operations cannot read or modify authentication, policy, audit-integrity or installed Binnacle state outside `SELF-MANAGE`. |
| **Credentials and information** | No credentials or `never-disclosable` values enter ChatGPT, command output, ordinary logs or audit payloads. |
| **Network boundary** | External connections reach only authorised effective targets and uncertain remote outcomes remain uncertain. |
| **Concurrency** | Conflicting operations never hold incompatible ownership; retries do not duplicate non-idempotent effects. |
| **Evidence and audit** | Every consequential outcome has complete structured local evidence and an integrity-protected audit record. |
| **Resource protection** | Ordinary work cannot exhaust Binnacle's status, cancellation, audit-completion or safe-stop capacity. |
| **Self-management** | A staged Binnacle change can be built, tested, restarted, verified and recovered without an ordinary command bypassing the control plane. |
| **No Companion dependency** | All V1 supported workflows complete with ChatGPT and Binnacle only; no external approval issuer or Companion is required. |
| **No Sampling** | Binnacle neither declares, requests nor uses MCP Sampling or equivalent server-initiated model generation. |

### 20.3 Mandatory adversarial cases

V1 tests must include:

- a model statement claiming owner approval for a locally denied operation;
- a conversation identifier presented as controller identity;
- stale discovery showing a now-disabled tool;
- changed target state between preparation and execution;
- duplicate non-idempotent invocation;
- disconnect during long-running work;
- cancellation acknowledged before local stop is verified;
- command escape outside the authorised workspace;
- command access to Binnacle policy or authentication material;
- untrusted repository content attempting to invoke another capability;
- command output containing a credential;
- unexpected redirect or metadata-network target;
- storage or process exhaustion while status and cancellation remain available;
- Binnacle service update that fails health verification;
- restart with a retained `uncertain` operation;
- two ChatGPT conversations under one controller attempting conflicting work;
- an MCP Task handle treated as operation identity or authority;
- any Binnacle Sampling request.

## 21. Canonical Invariants

1. **ChatGPT is the only reasoning, planning, diagnostic and multi-device coordination agent.**
2. **Binnacle exposes deterministic device-local observation and execution capabilities only.**
3. **One Binnacle instance manages one Raspberry Pi and never discovers, calls or coordinates another instance.**
4. **Binnacle V1 works directly with ChatGPT through MCP and has no mandatory Companion, approval issuer or separate owner-control service.**
5. **The authenticated controller and local policy are the authoritative server-side basis for normal operation admission.**
6. **A ChatGPT confirmation, model assertion, conversation identifier or client metadata value cannot expand Binnacle authority.**
7. **Semantic ambiguity never expands permission; missing material inputs fail closed.**
8. **Actual freshly verified device state governs current operational facts.**
9. **Capability discovery is advisory; invocation-time authentication, policy and state validation are authoritative.**
10. **Every exposed operation has a stable semantic identity, versioned contract and explicit maximum effects.**
11. **Every consequential operation has one durable Binnacle operation identity independent of MCP calls and ChatGPT conversations.**
12. **Retries reconcile the same operation identity and never repeat an uncertain or non-idempotent effect as fresh work.**
13. **An MCP protocol or cancellation success is not proof of Binnacle operation success or verified cancellation.**
14. **Silence or absence of another ChatGPT request has no lifecycle effect by itself.**
15. **After declared supervision loss, only the operation's predefined protective effect may proceed; later recovery is a new operation.**
16. **A prepared operation creates no authority and cannot substitute for controller authentication or local policy.**
17. **Local policy changes are not ordinary MCP operations in V1.**
18. **General-purpose execution authority includes every descendant, helper, inherited descriptor and indirect local effect.**
19. **An authority dimension that cannot be confined is declared broader or the capability remains unsupported.**
20. **General-purpose work cannot directly read or modify Binnacle authentication, policy, audit-integrity, recovery or installed executable state.**
21. **Credentials, raw secrets and protected control-plane material never enter model-visible results, command interfaces, ordinary logs or audit payloads.**
22. **Every result payload has a prospective information class and errors cannot become an alternative disclosure path.**
23. **External-system reachability and credential presence never imply authority.**
24. **Every external connection and transfer remains within explicit effective-target, action, direction and volume bounds.**
25. **Uncertain remote outcomes remain uncertain and are never converted into local success.**
26. **Destructive operations require exact targets, explicit local enablement, current-state verification and truthful recovery semantics.**
27. **Hardware operations require validated identity, reservations, limits and a predefined safe state; owner confirmation cannot replace required interlocks.**
28. **Binnacle preserves sufficient control-plane capacity for status, cancellation, audit completion and safe stop.**
29. **Only Binnacle advances authoritative local operation lifecycle state.**
30. **A persistent workload outlives its creating operation only after explicit transfer to a managed-workload identity and contract.**
31. **Owner-configurable unattended general automation is outside V1; only foundational protective rules may act without a new ChatGPT request.**
32. **Binnacle verifies local outcomes only; ChatGPT assesses broader workflow completion and the owner remains the final human authority.**
33. **If the highest local trust boundary is compromised, Binnacle cannot prove or repair its own trust and requires local rebuild or reassessment.**
34. **Binnacle self-development is permitted only through controlled operations; Binnacle never decides to modify itself.**
35. **MCP Tasks, resources, prompts and metadata supply neither authority nor reasoning.**
36. **Binnacle V1 does not use MCP Sampling or equivalent server-initiated model generation.**
37. **Actual ChatGPT compatibility is a tested profile, not an inference from generic MCP support or documentation.**
38. **The initial V1 support claim is limited to its named bootstrap workflows and does not imply the full host, software and hardware catalogues.**
39. **No supported V1 workflow may depend on an external Companion or approval service.**
40. **After V1 connection, ChatGPT may use Binnacle to build later versions, but all reasoning and initiative remain with ChatGPT and the owner.**

## 22. Excluded Implementation Decisions

This specification intentionally does not define:

- programming language or runtime;
- internal module or package structure;
- storage or database technology;
- operating-system service layout;
- concrete sandbox technology;
- individual MCP tool names or JSON schemas;
- transport deployment configuration;
- packaging and installer design;
- policy file format;
- audit storage format;
- test framework or CI provider.

Those decisions must be derived from the frozen feature and interface contracts rather than changing the product boundary implicitly.

### 22.1 Downstream handoff

| ID | Stage | Route | Depends on | Required output |
| --- | --- | --- | --- | --- |
| `MCP-FEAS` | Actual ChatGPT MCP feasibility investigation | RUN first | V17 feature scope and access to the target ChatGPT account/product | Evidence-backed supported profile or explicit blockers covering authentication, discovery, tools, resources, long-running work, Tasks, cancellation, MRTR/elicitation, field visibility, result limits and Sampling absence. |
| `MCP-INTERFACE` | Binnacle MCP Interface Design | RUN after initial feasibility, iterate with it | V17 and `MCP-FEAS` | Versioned operation catalogue, tool/resource contracts, lifecycle/result/error schemas, discovery and compatibility rules. |
| `SEC` | Binnacle security and threat model | RUN in parallel with interface work | V17, device assumptions and preliminary MCP profile | Threat model, security requirements, accepted residual risks and required negative tests for the server-only boundary. |
| `ARCH` | Logical architecture | RUN after feasible MCP boundary and initial SEC | `MCP-INTERFACE`, `SEC`, `MCP-FEAS` | Components, state ownership, isolation, privilege, failure containment and dependency direction. |
| `TEST` | Test and evaluation design | RUN with architecture | V17, interface and SEC | Reproducible fixtures and evidence oracle for Section 20. |
| `TECH-PROV` | Provisional technology choices | RUN after architecture | `ARCH`, `SEC`, `TEST` | Reversible runtime, storage, transport, sandbox, packaging and service choices. |
| `IMPL-V1` | Bootstrap V1 implementation | RUN after provisional decisions | `TECH-PROV`, initial tests | Runnable B1/S1/H1/R1 server connected to ChatGPT. |
| `MCP-CONF` | Full ChatGPT conformance | RUN against implementation | `IMPL-V1`, complete interface tests | Validated ChatGPT profile and end-to-end conformance matrix. |
| `SELF-HOST` | ChatGPT-driven Binnacle expansion | RUN after stable V1 connection | Passing V1 gates | Later capabilities developed through Binnacle under `SELF-MANAGE`, with new contracts and regression evidence. |
| `ARCH-REC` | Architecture/product reconciliation | DEFER | Evidence that architecture cannot satisfy an invariant | Explicit owner decision to narrow, revise or reject the conflicting feature; no silent implementation workaround. |

The correct immediate sequence is:

```text
V17 server-only feature design
        ↓
MCP-FEAS ─────┐
              ├─→ MCP-INTERFACE
SEC ──────────┘
        ↓
ARCH + TEST
        ↓
TECH-PROV
        ↓
IMPL-V1
        ↓
Connect to ChatGPT
        ↓
MCP-CONF
        ↓
ChatGPT uses Binnacle to build later versions
```

No `PX`, `COMP-FEAS` or Companion repository is required for Binnacle V1.
