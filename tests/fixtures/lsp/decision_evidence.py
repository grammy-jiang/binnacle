"""Invented P3.6 unit data only. Never real provider measurements or reviews."""

from typing import Any, TypeVar

from binnacle.config_development_intelligence import (
    DevelopmentIntelligenceSettings,
    DevelopmentProviderSettings,
)
from scripts.lsp_p36_evidence import (
    Artifact,
    CapabilityEvidence,
    Envelope,
    Evidence,
    EvidenceBundle,
    Identity,
    MeasurementEvidence,
    PolicyRequest,
    Review,
    SafetyEvidence,
    WarmSample,
    fingerprint,
)

EvidenceType = TypeVar("EvidenceType", bound=Evidence)


def reviewed(data: EvidenceType) -> EvidenceType:
    """Simulate an independent attestation, without contacting any reviewer."""
    return data.model_copy(
        update={
            "review": Review(
                reviewer="synthetic-reviewer",
                payload_sha256=data.payload_digest(),
                verdict="GO",
                record=Artifact(reference="synthetic-review", sha256="b" * 64),
            )
        }
    )


def inputs() -> tuple[PolicyRequest, EvidenceBundle]:
    """Supply wholly synthetic positive control; no executable is accessed."""
    profile = DevelopmentProviderSettings(
        enabled=True,
        source="trusted_absolute",
        mode="explicit_trust_only",
        executable="/synthetic/never-execute",
        languages=("python",),
    )
    identity = Identity(
        provider="pyright",
        provider_version="synthetic-1",
        executable_sha256="a" * 64,
        profile_sha256=fingerprint(profile),
        adapter_sha256="b" * 64,
        binnacle_commit="c" * 40,
        host="synthetic-host",
        os="linux",
        arch="aarch64",
        runtime="synthetic-runtime",
        environment_sha256="d" * 64,
        corpus_sha256="e" * 64,
        gold_sha256="f" * 64,
        language="python",
        method="textDocument/definition",
        workload="medium_synthetic",
        measurement_path="raw_lsp",
    )
    envelope = Envelope(
        max_resident_servers=1, idle_timeout_s=120.0, request_timeout_s=30.0
    )
    request = PolicyRequest(
        schema_version=1,
        target=identity,
        settings=DevelopmentIntelligenceSettings(
            enabled=True, profiles={"pyright": profile}
        ),
        requested_envelope=envelope,
        trusted_reviewers=("synthetic-reviewer",),
    )
    common: dict[str, Any] = {
        "schema_version": 1,
        "identity": identity,
        "producer": "synthetic-author",
        "run_id": "synthetic-run",
        "captured_at_utc": "2026-10-22T00:00:00Z",
        "artifacts": (Artifact(reference="synthetic-source", sha256="a" * 64),),
        "final": True,
    }
    safety = SafetyEvidence(
        **common,
        stage="P3.3",
        classification="explicit_trust_only",
        subprocesses_trusted=True,
        project_execution_controlled=True,
        filesystem_effects_accounted=True,
        network_effects_accounted=True,
        cleanup_verified=True,
    )
    capability = CapabilityEvidence(
        **common,
        stage="P3.4",
        installation="trusted_absolute",
        protocol="advertised",
    )
    measurement = MeasurementEvidence(
        **common,
        stage="P3.5",
        correctness="fixture_pass",
        resident_settled=True,
        same_process=True,
        warm=tuple(
            WarmSample(latency_ms=float(n), gold_passed=True) for n in range(1, 31)
        ),
        tree_rss_mib=(100.0,) * 30,
        idle_tree_cpu_pct=(0.5,) * 30,
        complete_process_tree=True,
        cold_start_ms=100.0,
        settle_ms=200.0,
        soak_duration_s=600.0,
        soak_passed=True,
        cleanup_verified=True,
        tested_envelope=envelope,
        capacity_eviction_passed=True,
        deadline_passed=True,
        idle_eviction_passed=True,
    )
    bundle = EvidenceBundle(
        schema_version=1,
        safety=reviewed(safety),
        capability=reviewed(capability),
        measurement=reviewed(measurement),
    )
    return request, bundle
