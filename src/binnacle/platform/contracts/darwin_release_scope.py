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


DARWIN_RELEASE_SCOPE: Mapping[str, ReleaseDecision] = MappingProxyType(
    {
        "read_file": _pending("read_file", "CR2"),
        "list_files": _pending("list_files", "CR2"),
        "search_text": _pending("search_text", "CR2"),
        "edit_file": _pending("edit_file", "CR2"),
        "write_file": _pending("write_file", "CR2"),
        "run_command": _pending("run_command", "CR1a"),
        "job_status": _pending("job_status", "CR1a"),
        "stop_job": _pending("stop_job", "never"),
    }
)
FILE_TOOLS = ("read_file", "list_files", "search_text", "edit_file", "write_file")
