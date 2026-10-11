"""Committed Darwin release decisions; only a reviewed source change enables tools.

No environment, configuration, CLI or request flag participates in this table.
Composition may receive an explicit replacement mapping in tests only.

Interface 1.2.0: rows are chosen from the composed job owner. The embedded
owner keeps the reviewed LIMITED rows below. The manager owner targets
"full_with_disclosure": AVAILABLE plus an explicit, non-empty disclosure scope.
There is no FULL_WITH_DISCLOSURE capability state, and an unreachable manager
never selects LIMITED rows. Manager command rows stay UNAVAILABLE until J-CR.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from binnacle.platform.contracts.capability_contracts import Capability, CapabilityState
from binnacle.platform.contracts.process_contracts import JobOwnerKind


@dataclass(frozen=True)
class ReleaseDecision:
    capability: Capability
    decision_target: str
    enabling_gate: str
    decision_reference: str
    disclosures: tuple[str, ...] = ()


def _pending(tool: str, gate: str) -> ReleaseDecision:
    return ReleaseDecision(
        Capability(CapabilityState.UNAVAILABLE, "review_pending", tool),
        "unavailable" if tool == "stop_job" else "limited",
        gate,
        f"CAPABILITY-DECISION.json#/scope_decision/tool_by_tool/{tool}",
    )


def _limited(tool: str, gate: str, scope: str, reference: str) -> ReleaseDecision:
    return ReleaseDecision(
        Capability(CapabilityState.LIMITED, "reviewed_limited", scope),
        "limited",
        gate,
        reference,
    )


DARWIN_RELEASE_SCOPE: Mapping[str, ReleaseDecision] = MappingProxyType(
    {
        "read_file": _limited(
            "read_file",
            "CR2",
            "descriptor-contained read_file; replacement metadata limits",
            "reviews/cr2/CR2-SUPERVISOR-REVIEW-PART1.json; A4=ad5f22ff992c071769a68d0dfedbbc1bb2c0eac2; A5=e1c625086628e6d91f094f649ea7012216a64050; A6=989b69e38c48c73d39994aa021e4ecf79ccd8cb4; T0=6904a71a6093e04d9ed2c230df15f60195b6fd1a; B0=fd7343b3c30afbba503454a391bc034415eba8ff",
        ),
        "list_files": _limited(
            "list_files",
            "CR2",
            "descriptor-contained listing; bounded depth and documented glob differences",
            "reviews/cr2/CR2-SUPERVISOR-REVIEW-PART2.json; verdict_sha256=5ad12360eeee5b7e4966e01e5564e6a63f7f463a744266fb3d4b08eaddea0447; A4-a3=38e330ea04fefd585dbfa72070c621fab300b029; R2-delta-a2_sha256=f945e32654e5e224c8cae3fcb8e9afdb5f6f1ba14295193f4fb0072b78841791",
        ),
        "search_text": _limited(
            "search_text",
            "CR2",
            "descriptor-contained search; 16 MiB aggregate budget; oversized files skipped",
            "reviews/cr2/CR2-SUPERVISOR-REVIEW-PART2.json; verdict_sha256=5ad12360eeee5b7e4966e01e5564e6a63f7f463a744266fb3d4b08eaddea0447; A4-a3=38e330ea04fefd585dbfa72070c621fab300b029; R2-delta-a2_sha256=f945e32654e5e224c8cae3fcb8e9afdb5f6f1ba14295193f4fb0072b78841791",
        ),
        "edit_file": _limited(
            "edit_file",
            "CR2",
            "descriptor-contained edit_file; replacement metadata limits",
            "reviews/cr2/CR2-SUPERVISOR-REVIEW-PART1.json; A4=ad5f22ff992c071769a68d0dfedbbc1bb2c0eac2; A5=e1c625086628e6d91f094f649ea7012216a64050; A6=989b69e38c48c73d39994aa021e4ecf79ccd8cb4; T0=6904a71a6093e04d9ed2c230df15f60195b6fd1a; B0=fd7343b3c30afbba503454a391bc034415eba8ff",
        ),
        "write_file": _limited(
            "write_file",
            "CR2",
            "descriptor-contained write_file; replacement metadata limits",
            "reviews/cr2/CR2-SUPERVISOR-REVIEW-PART1.json; A4=ad5f22ff992c071769a68d0dfedbbc1bb2c0eac2; A5=e1c625086628e6d91f094f649ea7012216a64050; A6=989b69e38c48c73d39994aa021e4ecf79ccd8cb4; T0=6904a71a6093e04d9ed2c230df15f60195b6fd1a; B0=fd7343b3c30afbba503454a391bc034415eba8ff",
        ),
        "run_command": _limited(
            "run_command",
            "CR1a",
            "foreground owned-child only; max 50 s; descendants_unverified",
            "reviews/cr1/CR1A-SUPERVISOR-REVIEW.json; A2=b4946ec1b1a3aadbae55005aeb0314a14e9a5790; A2/FU1=0e23f9977fbaa70a04a0636ec267749fdf8ba9b3; A3=a1f91b7f2e39bcef5173858115fc6a31bb5f3400; B0=fd7343b3c30afbba503454a391bc034415eba8ff",
        ),
        "job_status": _limited(
            "job_status",
            "CR1a",
            "completed foreground history/output in memory; lost on restart",
            "reviews/cr1/CR1A-SUPERVISOR-REVIEW.json; A2=b4946ec1b1a3aadbae55005aeb0314a14e9a5790; A2/FU1=0e23f9977fbaa70a04a0636ec267749fdf8ba9b3; A3=a1f91b7f2e39bcef5173858115fc6a31bb5f3400; B0=fd7343b3c30afbba503454a391bc034415eba8ff",
        ),
        "stop_job": _pending("stop_job", "never"),
    }
)
FILE_TOOLS = ("read_file", "list_files", "search_text", "edit_file", "write_file")
COMMAND_TOOLS = ("run_command", "job_status", "stop_job")

FULL_WITH_DISCLOSURE = "full_with_disclosure"
MANAGER_DISCLOSURES: tuple[str, ...] = (
    "D-1: jobs of a lost manager are UNKNOWN; never adopted, never exited",
    "D-2: CPU/RSS accounting is sampled; membership_closed=false",
    "descendants_unverified=true: new sessions/process groups are not tracked",
)
_REQUIRED_DISCLOSURES = ("D-1:", "descendants_unverified=true")


def _manager_pending(tool: str) -> ReleaseDecision:
    return ReleaseDecision(
        Capability(CapabilityState.UNAVAILABLE, "review_pending", tool),
        FULL_WITH_DISCLOSURE,
        "J-CR",
        f"R4 DARWIN-DURABLE-JOBS-DESIGN.md#10; JCR-DESIGN-REVIEW.json; {tool}",
        MANAGER_DISCLOSURES,
    )


DARWIN_EMBEDDED_RELEASE_SCOPE = DARWIN_RELEASE_SCOPE
DARWIN_MANAGER_RELEASE_SCOPE: Mapping[str, ReleaseDecision] = MappingProxyType(
    {
        **{tool: DARWIN_RELEASE_SCOPE[tool] for tool in FILE_TOOLS},
        **{tool: _manager_pending(tool) for tool in COMMAND_TOOLS},
    }
)


def resolve_darwin_job_owner(configured: str) -> JobOwnerKind:
    """JCR-2: Darwin production composes the manager; embedded only when explicit.

    Reachability never participates: an unreachable manager is a per-call
    JOB_MANAGER_UNAVAILABLE error, picked up again as soon as it answers.
    """
    if configured in ("auto", "manager"):
        return "manager"
    if configured == "embedded":
        return "embedded"
    raise RuntimeError(f"unknown Darwin job owner {configured!r}")


def release_scope_for_owner(owner: JobOwnerKind) -> Mapping[str, ReleaseDecision]:
    """Select and validate committed rows of the composed owner, never reachability.

    Runtime gates (the A2 foreground runner for embedded) are checked again
    where the execution is composed.
    """
    if owner not in ("manager", "embedded"):
        raise RuntimeError(f"unknown Darwin job owner {owner!r}")
    scope = DARWIN_MANAGER_RELEASE_SCOPE if owner == "manager" else DARWIN_RELEASE_SCOPE
    validate_release_rows(scope, owner)
    validate_owner_command_states(
        {tool: scope[tool].capability.state.value for tool in COMMAND_TOOLS}, owner
    )
    return scope


def validate_release_rows(
    scope: Mapping[str, ReleaseDecision], owner: JobOwnerKind
) -> None:
    """AVAILABLE command rows exist only under the manager, with full disclosure."""
    for tool in COMMAND_TOOLS:
        row = scope.get(tool)
        if row is None or row.capability.state != CapabilityState.AVAILABLE:
            continue
        if owner != "manager" or row.decision_target != FULL_WITH_DISCLOSURE:
            raise RuntimeError(f"Darwin {tool} AVAILABLE requires the manager owner")
        if not all(
            any(item.startswith(needle) for item in row.disclosures)
            for needle in _REQUIRED_DISCLOSURES
        ):
            raise RuntimeError(f"Darwin {tool} AVAILABLE requires its disclosures")


def validate_owner_command_states(
    states: Mapping[str, str], owner: JobOwnerKind, execution: object = None
) -> None:
    """Owner-conditioned invariant (1.2.0); replaces the unconditional stop_job rule.

    Embedded: stop_job stays UNAVAILABLE. Manager (JCR-2): command rows are
    only UNAVAILABLE or AVAILABLE, never LIMITED, and no embedded execution
    is composed beside it. Host-independent, like the rule it replaces.
    """
    if owner == "embedded":
        if states.get("stop_job", "UNAVAILABLE") != "UNAVAILABLE":
            raise RuntimeError("Darwin stop_job must remain UNAVAILABLE when embedded")
        return
    if owner != "manager":
        raise RuntimeError(f"unknown Darwin job owner {owner!r}")
    if execution is not None:
        raise RuntimeError("Darwin manager owner composes no embedded execution")
    for tool in COMMAND_TOOLS:
        if states.get(tool, "UNAVAILABLE") not in ("UNAVAILABLE", "AVAILABLE"):
            raise RuntimeError(
                f"Darwin manager owner serves {tool} only UNAVAILABLE or AVAILABLE"
            )
    if states.get("run_command", "UNAVAILABLE") != "AVAILABLE" and any(
        states.get(tool, "UNAVAILABLE") == "AVAILABLE"
        for tool in ("job_status", "stop_job")
    ):
        raise RuntimeError("Darwin manager job tools require run_command AVAILABLE")
