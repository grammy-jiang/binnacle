"""Optional deterministic P3.6 analysis, never imported by runtime composition.

GO means only an evidence-supported private experiment at the exact input
scope. This module cannot authorize execution, READ, P4/P5 or deployment.
"""

from __future__ import annotations

import math
from typing import Literal

from binnacle.features.development_intelligence.lsp_profile_assessment import (
    assess_provider_profile,
)
from scripts.lsp_p36_evidence import (
    Envelope,
    Evidence,
    EvidenceBundle,
    MeasurementEvidence,
    PolicyRequest,
    Record,
    fingerprint,
)

Verdict = Literal["GO", "REWORK", "NO-GO"]
MIN_SAMPLES = 30  # Exploratory floor from testing-performance.md, not stability proof.
MIN_SOAK_SECONDS = 60  # A second of "soak" is not a lifecycle check.


class AuditEntry(Record):
    """Retain digests for accepted and rejected payloads alike."""

    stage: str
    payload_sha256: str | None
    reasons: tuple[str, ...]


class Observed(Record):
    """Sample statistics, not future upper bounds or CPU/RSS quotas."""

    warm_samples: int
    warm_p50_ms: float
    warm_p95_ms: float
    warm_p99_ms: float
    max_observed_tree_rss_mib: float
    max_observed_idle_tree_cpu_pct: float


class Decision(Record):
    """Versioned audit result; no launch or release authorization field."""

    policy_version: Literal["p3.6-v1"] = "p3.6-v1"
    request_sha256: str
    evidence_sha256: str
    selection: Verdict
    resource: Verdict
    read: Literal["NO-GO"] = "NO-GO"
    public_release: Literal["NO-GO"] = "NO-GO"
    # No cryptographic or trusted external reviewer attestation is verified by
    # this offline script; a synthetic positive fixture cannot grant authority.
    attestations_verified: Literal[False] = False
    reasons: tuple[str, ...]
    audit: tuple[AuditEntry, ...]
    observed: Observed | None = None
    tested_envelope: Envelope | None = None


def _audit(stage: str, evidence: Evidence | None, request: PolicyRequest) -> AuditEntry:
    reasons: list[str] = []
    if evidence is None:
        return AuditEntry(stage=stage, payload_sha256=None, reasons=("missing",))
    if evidence.identity != request.target:
        reasons.append("identity_mismatch")
    if not evidence.final:
        reasons.append("not_final")
    review = evidence.review
    if review is None:
        reasons.append("independent_review_missing")
    else:
        if review.reviewer == evidence.producer:
            reasons.append("self_review")
        if review.reviewer not in request.trusted_reviewers:
            reasons.append("reviewer_unverified")
        if review.payload_sha256 != evidence.payload_digest():
            reasons.append("review_digest_mismatch")
        if review.verdict == "NO-GO":
            reasons.append("review_no_go")
        elif review.verdict != "GO":
            reasons.append("review_not_go")
    return AuditEntry(
        stage=stage, payload_sha256=evidence.payload_digest(), reasons=tuple(reasons)
    )


def _measurement_reasons(
    data: MeasurementEvidence, request: PolicyRequest
) -> list[str]:
    expected = (
        "real_repo_pass"
        if request.target.workload == "real_repository"
        else "fixture_pass"
    )
    checks = {
        "correctness_unproven": data.correctness == expected,
        "warm_sample_too_small": len(data.warm) >= MIN_SAMPLES,
        "gold_failure": all(sample.gold_passed for sample in data.warm),
        "resident_warm_unproven": data.resident_settled and data.same_process,
        "rss_sample_too_small": len(data.tree_rss_mib) >= MIN_SAMPLES,
        "rss_zero_or_negative": all(v > 0 for v in data.tree_rss_mib),
        "latency_zero_or_negative": all(v.latency_ms > 0 for v in data.warm),
        "cpu_sample_too_small": len(data.idle_tree_cpu_pct) >= MIN_SAMPLES,
        "process_tree_incomplete": data.complete_process_tree,
        "cold_settle_missing": data.cold_start_ms is not None
        and data.settle_ms is not None,
        "soak_unproven": data.soak_passed
        and (data.soak_duration_s or 0) >= MIN_SOAK_SECONDS,
        "cleanup_unverified": data.cleanup_verified,
        "resource_envelope_mismatch": data.tested_envelope
        == request.requested_envelope,
        "capacity_eviction_unproven": data.capacity_eviction_passed,
        "deadline_unproven": data.deadline_passed,
        "idle_eviction_unproven": data.idle_eviction_passed,
        "workload_too_small": request.target.workload != "micro_synthetic",
    }
    return [reason for reason, passed in checks.items() if not passed]


def _observed(data: MeasurementEvidence) -> Observed:
    ordered = sorted(sample.latency_ms for sample in data.warm)
    return Observed(
        warm_samples=len(ordered),
        warm_p50_ms=ordered[math.ceil(len(ordered) * 0.50) - 1],
        warm_p95_ms=ordered[math.ceil(len(ordered) * 0.95) - 1],
        warm_p99_ms=ordered[math.ceil(len(ordered) * 0.99) - 1],
        max_observed_tree_rss_mib=max(data.tree_rss_mib),
        max_observed_idle_tree_cpu_pct=max(data.idle_tree_cpu_pct),
    )


def evaluate(request: PolicyRequest, bundle: EvidenceBundle) -> Decision:
    """Validate again at the boundary; reject model_copy/construct bypasses.

    All refusal reasons are collected in a fixed order. Invalid schemas raise
    ValidationError; the CLI translates that into a NO-GO with no measurements.
    """
    request = PolicyRequest.model_validate_json(request.model_dump_json())
    bundle = EvidenceBundle.model_validate_json(bundle.model_dump_json())
    profile = request.settings.profiles.get(request.target.provider)
    admission = assess_provider_profile(request.settings, request.target.provider)
    blockers: list[str] = []
    if not admission.private_launch_eligible:
        blockers.append("p3.1:" + admission.reason)
    if profile is None or fingerprint(profile) != request.target.profile_sha256:
        blockers.append("profile_identity_mismatch")
    if request.target.provider == "pyright" and request.target.language != "python":
        blockers.append("language_not_allowed")
    envelope = request.requested_envelope
    if envelope.max_resident_servers > request.settings.max_resident_servers:
        blockers.append("configured_resident_limit_exceeded")
    if envelope.idle_timeout_s != request.settings.idle_timeout_s:
        blockers.append("configured_idle_timeout_mismatch")
    if envelope.request_timeout_s != request.settings.request_timeout_s:
        blockers.append("configured_request_timeout_mismatch")
    audit = tuple(
        _audit(stage, data, request)
        for stage, data in (
            ("P3.3", bundle.safety),
            ("P3.4", bundle.capability),
            ("P3.5", bundle.measurement),
        )
    )
    gaps = [f"{entry.stage}:{reason}" for entry in audit for reason in entry.reasons]
    safety = bundle.safety
    if safety is not None:
        if safety.classification != "explicit_trust_only":
            blockers.append("safety:explicit_trust_required")
        for field in (
            "subprocesses_trusted",
            "project_execution_controlled",
            "filesystem_effects_accounted",
            "network_effects_accounted",
            "cleanup_verified",
        ):
            if not getattr(safety, field):
                blockers.append("safety:" + field)
    capability = bundle.capability
    if capability is not None:
        if capability.installation not in ("service_found", "trusted_absolute"):
            blockers.append("provider_unavailable")
        if capability.protocol != "advertised":
            blockers.append("method_not_advertised")
    data = bundle.measurement
    if data is not None:
        gaps.extend("P3.5:" + reason for reason in _measurement_reasons(data, request))
        if data.correctness == "failed" or any(
            not sample.gold_passed for sample in data.warm
        ):
            blockers.append("incorrect_results")
    rejected_review = any("review_no_go" in entry.reasons for entry in audit)
    verdict: Verdict = (
        "NO-GO" if blockers or rejected_review else "REWORK" if gaps else "GO"
    )
    accepted = data is not None and verdict == "GO"
    return Decision(
        request_sha256=fingerprint(request),
        evidence_sha256=fingerprint(bundle),
        selection=verdict,
        resource=verdict,
        reasons=tuple(blockers + gaps),
        audit=audit,
        observed=_observed(data) if accepted and data is not None else None,
        tested_envelope=envelope if accepted else None,
    )
