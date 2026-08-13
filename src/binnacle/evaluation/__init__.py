"""Evidence-backed ChatGPT MCP evaluation helpers.

Public exports are loaded lazily so standard-library-only operational tools can import
their narrow evaluation submodules even when optional validation dependencies are not
installed yet.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from binnacle.evaluation.bundle import (
        EvaluationVerificationError,
        FinalizedBundle,
        finalize_evaluation,
        verify_evaluation_manifest,
    )
    from binnacle.evaluation.cases import FrozenCaseSet, FrozenEvaluationCase
    from binnacle.evaluation.phase10_acceptance import (
        AcceptanceManifestError,
        AcceptanceReport,
        AcceptanceVerdict,
        create_phase10_skeleton,
        evaluate_phase10_manifest,
    )
    from binnacle.evaluation.profile import FrozenEvaluationProfile

_EXPORTS = {
    "AcceptanceManifestError": (
        "binnacle.evaluation.phase10_acceptance",
        "AcceptanceManifestError",
    ),
    "AcceptanceReport": ("binnacle.evaluation.phase10_acceptance", "AcceptanceReport"),
    "AcceptanceVerdict": ("binnacle.evaluation.phase10_acceptance", "AcceptanceVerdict"),
    "EvaluationVerificationError": (
        "binnacle.evaluation.bundle",
        "EvaluationVerificationError",
    ),
    "FinalizedBundle": ("binnacle.evaluation.bundle", "FinalizedBundle"),
    "FrozenCaseSet": ("binnacle.evaluation.cases", "FrozenCaseSet"),
    "FrozenEvaluationCase": ("binnacle.evaluation.cases", "FrozenEvaluationCase"),
    "FrozenEvaluationProfile": ("binnacle.evaluation.profile", "FrozenEvaluationProfile"),
    "create_phase10_skeleton": (
        "binnacle.evaluation.phase10_acceptance",
        "create_phase10_skeleton",
    ),
    "evaluate_phase10_manifest": (
        "binnacle.evaluation.phase10_acceptance",
        "evaluate_phase10_manifest",
    ),
    "finalize_evaluation": ("binnacle.evaluation.bundle", "finalize_evaluation"),
    "verify_evaluation_manifest": (
        "binnacle.evaluation.bundle",
        "verify_evaluation_manifest",
    ),
}

__all__ = [
    "AcceptanceManifestError",
    "AcceptanceReport",
    "AcceptanceVerdict",
    "EvaluationVerificationError",
    "FinalizedBundle",
    "FrozenCaseSet",
    "FrozenEvaluationCase",
    "FrozenEvaluationProfile",
    "create_phase10_skeleton",
    "evaluate_phase10_manifest",
    "finalize_evaluation",
    "verify_evaluation_manifest",
]


def __getattr__(name: str) -> Any:
    """Resolve the established package-level API without eager optional imports."""

    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Include lazy public exports in interactive discovery."""

    return sorted({*globals(), *__all__})
