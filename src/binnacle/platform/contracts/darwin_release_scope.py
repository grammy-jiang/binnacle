"""Committed Darwin release decisions; only a reviewed source change enables tools.

No environment, configuration, CLI or request flag participates in this table.
Composition may receive an explicit replacement mapping in tests only.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from binnacle.platform.contracts.capability_contracts import Capability, CapabilityState


@dataclass(frozen=True)
class ReleaseDecision:
    capability: Capability
    decision_target: str
    enabling_gate: str
    decision_reference: str


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
