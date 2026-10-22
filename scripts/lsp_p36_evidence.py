"""Versioned offline P3.6 inputs. These records are attestations, not authority.

Importers must verify raw artifacts and reviewer identity outside this module.
No path, executable, URL or artifact reference in evidence is dereferenced.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from binnacle.config_development_intelligence import (
    DevelopmentIntelligenceSettings,
    ProviderName,
)

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Text = Annotated[str, Field(min_length=1, max_length=256, pattern=r"\S")]
Number = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Version = Annotated[int, Field(ge=1, le=1)]
Method = Literal[
    "textDocument/definition",
    "textDocument/references",
    "textDocument/hover",
    "textDocument/documentSymbol",
    "workspace/symbol",
]


class Record(BaseModel):
    """Reject unknown fields, scalar coercion and accidental mutation."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


def fingerprint(record: BaseModel) -> str:
    """Stable canonical JSON digest, including schema versions and null fields."""
    encoded = json.dumps(
        record.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


class Identity(Record):
    """Exact compatibility key; no implicit OS, language or workload promotion."""

    provider: ProviderName
    provider_version: Text
    executable_sha256: Digest
    profile_sha256: Digest
    adapter_sha256: Digest
    binnacle_commit: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    host: Text
    os: Text
    arch: Text
    runtime: Text
    environment_sha256: Digest
    corpus_sha256: Digest
    gold_sha256: Digest
    language: Text
    method: Method
    workload: Literal["micro_synthetic", "medium_synthetic", "real_repository"]
    measurement_path: Literal["raw_lsp", "private_integrated"]


class Envelope(Record):
    """Explicit experiment settings, never an inferred safe resource limit."""

    max_resident_servers: Annotated[int, Field(ge=1, le=8)]
    idle_timeout_s: Annotated[float, Field(ge=0, le=3600, allow_inf_nan=False)]
    request_timeout_s: Annotated[float, Field(gt=0, le=120, allow_inf_nan=False)]


class Artifact(Record):
    """Opaque audit reference to retained, externally verified source bytes."""

    reference: Text
    sha256: Digest


class Review(Record):
    """A separately verified reviewer must bind the complete evidence payload."""

    reviewer: Text
    payload_sha256: Digest
    verdict: Literal["GO", "REWORK", "NO-GO"]
    record: Artifact


class Evidence(Record):
    """Common provenance. Final status and review are necessary, not sufficient."""

    schema_version: Version
    identity: Identity
    producer: Text
    run_id: Text
    captured_at_utc: Annotated[
        str, Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
    ]
    artifacts: Annotated[tuple[Artifact, ...], Field(min_length=1, max_length=32)]
    final: bool = False
    review: Review | None = None

    def payload_digest(self) -> str:
        """Bind review to all fields except the review itself."""
        return fingerprint(self.model_copy(update={"review": None}))


class SafetyEvidence(Evidence):
    """P3.3 explicit-trust audit; cannot certify READ in this policy version."""

    stage: Literal["P3.3"]
    classification: Literal["not_audited", "benchmark_only", "explicit_trust_only"]
    subprocesses_trusted: bool = False
    project_execution_controlled: bool = False
    filesystem_effects_accounted: bool = False
    network_effects_accounted: bool = False
    cleanup_verified: bool = False


class CapabilityEvidence(Evidence):
    """P3.4 discovery/initialize is distinct from semantic correctness."""

    stage: Literal["P3.4"]
    installation: Literal["service_found", "trusted_absolute", "absent", "not_checked"]
    protocol: Literal["advertised", "not_advertised", "unprobed"]


class WarmSample(Record):
    """A failed gold result is never admitted as fast performance."""

    latency_ms: Number
    gold_passed: bool


class MeasurementEvidence(Evidence):
    """P3.5 observations at one exact scope and tested resource envelope."""

    stage: Literal["P3.5"]
    correctness: Literal["fixture_pass", "real_repo_pass", "failed", "unprobed"]
    resident_settled: bool = False
    same_process: bool = False
    warm: Annotated[tuple[WarmSample, ...], Field(max_length=10000)] = ()
    tree_rss_mib: Annotated[tuple[Number, ...], Field(max_length=10000)] = ()
    idle_tree_cpu_pct: Annotated[tuple[Number, ...], Field(max_length=10000)] = ()
    complete_process_tree: bool = False
    cold_start_ms: Number | None = None
    settle_ms: Number | None = None
    soak_duration_s: Number | None = None
    soak_passed: bool = False
    cleanup_verified: bool = False
    tested_envelope: Envelope | None = None
    capacity_eviction_passed: bool = False
    deadline_passed: bool = False
    idle_eviction_passed: bool = False


class EvidenceBundle(Record):
    """Missing stages are represented explicitly rather than invented."""

    schema_version: Version
    safety: SafetyEvidence | None = None
    capability: CapabilityEvidence | None = None
    measurement: MeasurementEvidence | None = None


class PolicyRequest(Record):
    """Operator-owned input, separate from imported provider evidence."""

    schema_version: Version
    target: Identity
    settings: DevelopmentIntelligenceSettings
    requested_envelope: Envelope
    trusted_reviewers: Annotated[tuple[Text, ...], Field(max_length=32)] = ()
