"""P3.1: inert, conservative per-provider trust classification.

An operator declaring a provider, finding a binary, or passing language-server
functionality tests is NOT proof of READ-safety. In particular, an upstream
Pyright LSP request may write files without any client applyEdit callback.

This module does not resolve paths, inspect workspaces, import multilspy,
execute providers or make network requests. The P2.4 owner independently
validates the host-selected executable at the only actual launch boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from binnacle.config_development_intelligence import (
    DevelopmentIntelligenceSettings,
    ProviderName,
    ProviderSource,
)

TrustClassification = Literal[
    "not_audited",
    "benchmark_only",
    "explicit_trust_only",
    "audited_read_eligible",
]
TrustReason = Literal[
    "feature_disabled",
    "profile_absent",
    "profile_disabled",
    "benchmark_service_path",
    "unaudited_source_or_mode",
    "unaudited_process_options",
    "unaudited_language_profile",
    "provider_adapter_unavailable",
    "operator_explicit_trust_required",
]


@dataclass(frozen=True)
class ProfileAssessment:
    """Internal verdict; contains no executable path or workspace metadata.

    `private_launch_eligible` grants only access to the P2.4 *additional*
    admission checks. It does not spawn or authorize a new MCP tool.
    """

    provider: str
    classification: TrustClassification
    reason: TrustReason
    source: ProviderSource | None
    private_launch_eligible: bool = False
    read_eligible: bool = False


def assess_provider_profile(
    settings: DevelopmentIntelligenceSettings,
    provider: ProviderName = "pyright",
) -> ProfileAssessment:
    """Derive a fail-closed launch/trust classification without any I/O.

    The intentionally unreachable `audited_read_eligible` category requires a
    separate P3 OS side-effect and confinement certificate, unavailable from
    configuration alone. Do not add a config flag to promote this status.
    """
    profile = settings.profiles.get(provider)
    if not settings.enabled:
        return ProfileAssessment(provider, "not_audited", "feature_disabled", None)
    if profile is None:
        return ProfileAssessment(provider, "not_audited", "profile_absent", None)

    if not profile.enabled:
        return ProfileAssessment(
            provider, "not_audited", "profile_disabled", profile.source
        )
    if profile.source == "service_path" and profile.mode == "benchmark_only":
        # Discoverable at a host's approved service PATH for *future* audits;
        # never a client-selected repo .venv/node_modules path or launch grant.
        return ProfileAssessment(
            provider,
            "benchmark_only",
            "benchmark_service_path",
            profile.source,
        )
    if (
        profile.source != "trusted_absolute"
        or profile.mode != "explicit_trust_only"
        or not profile.executable
    ):
        return ProfileAssessment(
            provider,
            "not_audited",
            "unaudited_source_or_mode",
            profile.source,
        )
    if profile.argv or profile.env:
        # Even a trusted binary with unchecked environment or command-line
        # options must not enter the private P2.4 process owner.
        return ProfileAssessment(
            provider,
            "not_audited",
            "unaudited_process_options",
            profile.source,
        )
    if (
        provider == "pyright"
        and profile.languages
        and "python" not in profile.languages
    ):
        return ProfileAssessment(
            provider,
            "not_audited",
            "unaudited_language_profile",
            profile.source,
        )
    if provider != "pyright":
        # A declared trusted executable does not provide a Binnacle audited
        # process owner/adapter for any language except Python/Pyright yet.
        return ProfileAssessment(
            provider,
            "explicit_trust_only",
            "provider_adapter_unavailable",
            profile.source,
        )
    return ProfileAssessment(
        provider,
        "explicit_trust_only",
        "operator_explicit_trust_required",
        profile.source,
        private_launch_eligible=True,
        read_eligible=False,
    )
