"""P3.6 fails closed; all numbers/reviews here are invented unit controls."""

from __future__ import annotations

import json
import socket
import subprocess

import pytest
from pydantic import ValidationError

from binnacle.config_development_intelligence import DevelopmentIntelligenceSettings
from scripts.lsp_p36_evidence import (
    EvidenceBundle,
    PolicyRequest,
    fingerprint,
)
from scripts.lsp_p36_policy import evaluate
from tests.fixtures.lsp.decision_evidence import inputs, reviewed


def refused(decision):
    assert decision.selection in ("REWORK", "NO-GO")
    assert decision.resource != "GO"
    assert decision.observed is None and decision.tested_envelope is None
    assert decision.read == decision.public_release == "NO-GO"


def test_scoped_positive_control_is_deterministic_and_never_read(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("offline policy attempted I/O")

    request, bundle = inputs()
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr("builtins.open", forbidden)
    decision = evaluate(request, bundle)
    assert decision == evaluate(request, bundle)
    assert decision.selection == decision.resource == "GO"
    assert decision.attestations_verified is False
    assert decision.read == decision.public_release == "NO-GO"
    assert decision.observed.warm_samples == 30
    assert decision.observed.warm_p50_ms == 15
    assert decision.observed.warm_p95_ms == 29
    assert decision.observed.warm_p99_ms == 30
    assert decision.observed.max_observed_tree_rss_mib == 100
    assert decision.observed.max_observed_idle_tree_cpu_pct == 0.5
    assert decision.tested_envelope == request.requested_envelope
    assert decision.request_sha256 == fingerprint(request)
    assert decision.evidence_sha256 == fingerprint(bundle)


@pytest.mark.parametrize("stage", ["safety", "capability", "measurement"])
def test_missing_stage_refuses(stage):
    request, bundle = inputs()
    decision = evaluate(request, bundle.model_copy(update={stage: None}))
    refused(decision)
    assert any(entry.reasons == ("missing",) for entry in decision.audit)


@pytest.mark.parametrize("stage", ["safety", "capability", "measurement"])
@pytest.mark.parametrize(
    "change", ["draft", "missing", "self", "unknown", "digest", "rework", "no_go"]
)
def test_review_and_finality_are_required(stage, change):
    request, bundle = inputs()
    data = getattr(bundle, stage)
    if change == "draft":
        data = reviewed(data.model_copy(update={"final": False}))
    elif change == "missing":
        data = data.model_copy(update={"review": None})
    else:
        updates = {
            "self": {"reviewer": data.producer},
            "unknown": {"reviewer": "unverified-reviewer"},
            "digest": {"payload_sha256": "0" * 64},
            "rework": {"verdict": "REWORK"},
            "no_go": {"verdict": "NO-GO"},
        }
        data = data.model_copy(
            update={"review": data.review.model_copy(update=updates[change])}
        )
    decision = evaluate(request, bundle.model_copy(update={stage: data}))
    refused(decision)
    if change == "no_go":
        assert decision.selection == "NO-GO"


@pytest.mark.parametrize(
    "field,value",
    [
        ("provider", "clangd"),
        ("provider_version", "other"),
        ("executable_sha256", "0" * 64),
        ("profile_sha256", "0" * 64),
        ("adapter_sha256", "0" * 64),
        ("binnacle_commit", "0" * 40),
        ("host", "other-host"),
        ("os", "darwin"),
        ("arch", "x86_64"),
        ("runtime", "other-runtime"),
        ("environment_sha256", "0" * 64),
        ("corpus_sha256", "0" * 64),
        ("gold_sha256", "0" * 64),
        ("language", "javascript"),
        ("method", "textDocument/references"),
        ("workload", "real_repository"),
        ("measurement_path", "private_integrated"),
    ],
)
@pytest.mark.parametrize("stage", ["safety", "capability", "measurement"])
def test_every_identity_axis_must_match_in_every_stage(field, value, stage):
    request, bundle = inputs()
    data = getattr(bundle, stage)
    data = reviewed(
        data.model_copy(
            update={"identity": data.identity.model_copy(update={field: value})}
        )
    )
    decision = evaluate(request, bundle.model_copy(update={stage: data}))
    refused(decision)
    assert any("identity_mismatch" in entry.reasons for entry in decision.audit)


@pytest.mark.parametrize(
    "field,value",
    [
        ("subprocesses_trusted", False),
        ("project_execution_controlled", False),
        ("filesystem_effects_accounted", False),
        ("network_effects_accounted", False),
        ("cleanup_verified", False),
        ("classification", "benchmark_only"),
        ("classification", "not_audited"),
    ],
)
def test_trust_failure_is_no_go(field, value):
    request, bundle = inputs()
    data = reviewed(bundle.safety.model_copy(update={field: value}))
    decision = evaluate(request, bundle.model_copy(update={"safety": data}))
    refused(decision)
    assert decision.selection == "NO-GO"


@pytest.mark.parametrize(
    "field,value",
    [
        ("installation", "absent"),
        ("installation", "not_checked"),
        ("protocol", "not_advertised"),
        ("protocol", "unprobed"),
    ],
)
def test_discovery_is_not_capability_or_security(field, value):
    request, bundle = inputs()
    data = reviewed(bundle.capability.model_copy(update={field: value}))
    refused(evaluate(request, bundle.model_copy(update={"capability": data})))


@pytest.mark.parametrize(
    "field,value",
    [
        ("correctness", "unprobed"),
        ("correctness", "failed"),
        ("correctness", "real_repo_pass"),
        ("resident_settled", False),
        ("same_process", False),
        ("complete_process_tree", False),
        ("cold_start_ms", None),
        ("settle_ms", None),
        ("soak_duration_s", None),
        ("soak_duration_s", 0.0),
        ("soak_passed", False),
        ("cleanup_verified", False),
        ("tested_envelope", None),
        ("capacity_eviction_passed", False),
        ("deadline_passed", False),
        ("idle_eviction_passed", False),
    ],
)
def test_measurement_gaps_never_become_bounds(field, value):
    request, bundle = inputs()
    data = reviewed(bundle.measurement.model_copy(update={field: value}))
    refused(evaluate(request, bundle.model_copy(update={"measurement": data})))


@pytest.mark.parametrize("field", ["warm", "tree_rss_mib", "idle_tree_cpu_pct"])
@pytest.mark.parametrize("count", [0, 1, 8, 29])
def test_tiny_or_missing_samples_are_rejected(field, count):
    request, bundle = inputs()
    data = reviewed(
        bundle.measurement.model_copy(
            update={field: getattr(bundle.measurement, field)[:count]}
        )
    )
    refused(evaluate(request, bundle.model_copy(update={"measurement": data})))


def test_fast_wrong_answer_is_no_go_and_retained_in_audit():
    request, bundle = inputs()
    warm = list(bundle.measurement.warm)
    warm[0] = warm[0].model_copy(update={"latency_ms": 0.0, "gold_passed": False})
    data = reviewed(bundle.measurement.model_copy(update={"warm": tuple(warm)}))
    decision = evaluate(request, bundle.model_copy(update={"measurement": data}))
    refused(decision)
    assert decision.selection == "NO-GO"
    assert "incorrect_results" in decision.reasons
    assert decision.audit[2].payload_sha256 == data.payload_digest()


@pytest.mark.parametrize(
    "scope,correctness,expected",
    [
        ("micro_synthetic", "fixture_pass", "REWORK"),
        ("real_repository", "fixture_pass", "REWORK"),
        ("real_repository", "real_repo_pass", "GO"),
    ],
)
def test_workload_scope_is_explicit(scope, correctness, expected):
    request, bundle = inputs()
    target = request.target.model_copy(update={"workload": scope})
    request = request.model_copy(update={"target": target})
    stages = {}
    for key in ("safety", "capability", "measurement"):
        data = getattr(bundle, key).model_copy(update={"identity": target})
        if key == "measurement":
            data = data.model_copy(update={"correctness": correctness})
        stages[key] = reviewed(data)
    assert evaluate(request, bundle.model_copy(update=stages)).selection == expected


@pytest.mark.parametrize("limit", range(1, 9))
def test_resident_configuration_cap_is_preserved(limit):
    request, bundle = inputs()
    settings = request.settings.model_copy(update={"max_resident_servers": limit})
    request = request.model_copy(update={"settings": settings})
    assert evaluate(request, bundle).selection == "GO"
    if limit < 8:
        envelope = request.requested_envelope.model_copy(
            update={"max_resident_servers": limit + 1}
        )
        request = request.model_copy(update={"requested_envelope": envelope})
        data = reviewed(
            bundle.measurement.model_copy(update={"tested_envelope": envelope})
        )
        decision = evaluate(request, bundle.model_copy(update={"measurement": data}))
        refused(decision)
        assert "configured_resident_limit_exceeded" in decision.reasons


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_resident_servers", 2),
        ("idle_timeout_s", 60.0),
        ("request_timeout_s", 15.0),
    ],
)
def test_no_resource_setting_is_inferred(field, value):
    request, bundle = inputs()
    envelope = request.requested_envelope.model_copy(update={field: value})
    refused(
        evaluate(request.model_copy(update={"requested_envelope": envelope}), bundle)
    )


def test_default_off_and_missing_profile_are_no_go():
    request, bundle = inputs()
    for settings in (
        DevelopmentIntelligenceSettings(),
        DevelopmentIntelligenceSettings(enabled=True),
    ):
        decision = evaluate(request.model_copy(update={"settings": settings}), bundle)
        refused(decision)
        assert decision.selection == "NO-GO"


@pytest.mark.parametrize(
    "provider",
    [
        "typescript",
        "clangd",
        "rust_analyzer",
        "marksman",
        "bash",
        "make",
        "yaml",
        "json",
    ],
)
def test_breadth_evidence_cannot_expand_p31_allowlist(provider):
    request, bundle = inputs()
    target = request.target.model_copy(update={"provider": provider})
    settings = request.settings.model_copy(
        update={"profiles": {provider: request.settings.profiles["pyright"]}}
    )
    request = request.model_copy(update={"target": target, "settings": settings})
    stages = {
        key: reviewed(getattr(bundle, key).model_copy(update={"identity": target}))
        for key in ("safety", "capability", "measurement")
    }
    decision = evaluate(request, bundle.model_copy(update=stages))
    refused(decision)
    assert "p3.1:provider_adapter_unavailable" in decision.reasons


def test_profile_and_language_checks_are_independent_of_evidence():
    request, bundle = inputs()
    target = request.target.model_copy(
        update={"profile_sha256": "0" * 64, "language": "rust"}
    )
    decision = evaluate(request.model_copy(update={"target": target}), bundle)
    refused(decision)
    assert "language_not_allowed" in decision.reasons
    assert "profile_identity_mismatch" in decision.reasons


@pytest.mark.parametrize(
    "mutation",
    [
        "schema",
        "extra",
        "boolean",
        "negative",
        "nan",
        "infinite",
        "digest",
        "stage",
        "read",
    ],
)
def test_invalid_evidence_schema_rejected(mutation):
    _, bundle = inputs()
    raw = bundle.model_dump(mode="json")
    changes = {
        "schema": {"schema_version": 2},
        "extra": {"security_certified": True},
        "boolean": {"same_process": "true"},
        "negative": {"tree_rss_mib": [-1]},
        "nan": {"tree_rss_mib": [float("nan")]},
        "infinite": {"cold_start_ms": float("inf")},
        "digest": {
            "identity": {
                **raw["measurement"]["identity"],
                "executable_sha256": "missing",
            }
        },
        "stage": {"stage": "P3.4"},
        "read": {"read_eligible": True},
    }
    raw["measurement"].update(changes[mutation])
    with pytest.raises(ValidationError):
        EvidenceBundle.model_validate_json(json.dumps(raw))


@pytest.mark.parametrize("count", [0, 9, True, "2"])
def test_envelope_rejects_invalid_resident_count(count):
    request, _ = inputs()
    raw = request.model_dump(mode="json")
    raw["requested_envelope"]["max_resident_servers"] = count
    with pytest.raises(ValidationError):
        PolicyRequest.model_validate_json(json.dumps(raw))


def test_model_copy_cannot_bypass_validation_and_tampering_invalidates_review():
    request, bundle = inputs()
    with pytest.raises(ValidationError):
        evaluate(request, bundle.model_copy(update={"schema_version": 2}))
    changed = bundle.measurement.model_copy(update={"run_id": "tampered"})
    decision = evaluate(request, bundle.model_copy(update={"measurement": changed}))
    refused(decision)
    assert "P3.5:review_digest_mismatch" in decision.reasons


@pytest.mark.parametrize("version", [True, 1.0, "1", 0, 2])
def test_version_is_a_strict_supported_integer(version):
    request, bundle = inputs()
    for record, model in ((request, PolicyRequest), (bundle, EvidenceBundle)):
        raw = record.model_dump(mode="json")
        raw["schema_version"] = version
        with pytest.raises(ValidationError):
            model.model_validate_json(json.dumps(raw))


def test_canonical_fingerprint_survives_key_order_and_json_round_trip():
    request, bundle = inputs()
    reordered = json.dumps(dict(reversed(list(bundle.model_dump(mode="json").items()))))
    assert fingerprint(bundle) == fingerprint(
        EvidenceBundle.model_validate_json(reordered)
    )
    assert request == PolicyRequest.model_validate_json(request.model_dump_json())
