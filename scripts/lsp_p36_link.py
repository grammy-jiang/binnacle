"""Offline P3.3/P3.4/P3.5 evidence linking against an operator trust registry.

Verifies that three registry-authenticated review receipts bind one run, one
target and one Binnacle commit to the exact raw artifact bytes of each stage.
The result is a linkage report only: it never sets attestations_verified,
accepts OS confinement/resources, or leaves selection REWORK / READ NO-GO.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.lsp_p36_secure_io import PathPolicy, PathRefused, read_file
from scripts.lsp_p36_signed_review import (
    ReviewRefused,
    Stage,
    TrustedReview,
    verify_registry_review,
)
from scripts.lsp_p36_trust_registry import (
    REGISTRY_ENV,
    FileReplayLedger,
    RegistryRefused,
    ReplayLedger,
    load_trust_registry,
)

STAGES: tuple[Stage, ...] = ("P3.3", "P3.4", "P3.5")
ARTIFACT_MAX = 4 * 1024 * 1024
RECEIPT_MAX = 16 * 1024
REPO = Path(__file__).resolve().parents[1]
BLOCKERS = (
    "p33_os_confinement_and_resource_acceptance_unverified",
    "p34_pyright_method_identity_unverified",
    "p35_raw_events_and_gold_not_independently_replayed",
    "operator_registry_provenance_not_provable_from_agent_sandbox",
    "replay_ledger_same_account_unless_operator_isolated",
)


class LinkRefused(ValueError):
    """Fixed non-sensitive denial identifier."""


@dataclass(frozen=True)
class StageInput:
    """Operator-supplied stage pins; paths are untrusted evidence locations."""

    artifact: str
    evidence_sha256: str
    receipt: str


def evidence_policy() -> PathPolicy:
    """Evidence may be owned by this account or root; links and sharing refused."""
    return PathPolicy(
        owner_uids=frozenset({os.geteuid(), 0}),
        check_ancestors=False,
    )


def link_stage_evidence(
    *,
    registry_path: str | Path | None,
    registry_policy: PathPolicy,
    evidence_policy_: PathPolicy,
    ledger: ReplayLedger,
    registry_id: str,
    min_registry_serial: int,
    expected_registry_sha256: str,
    run_id: str,
    producer: str,
    binnacle_commit: str,
    target_sha256: str,
    stages: Mapping[str, StageInput],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return a REWORK/NO-GO linkage report or raise a fixed refusal."""
    if set(stages) != set(STAGES):
        raise LinkRefused("stage_evidence_missing_or_unknown")
    # Registry may not live in a directory that holds any supplied evidence.
    locations = [
        str(Path(item).parent)
        for entry in stages.values()
        for item in (entry.artifact, entry.receipt)
    ]
    roots = (*locations, str(REPO), os.getcwd())
    chosen = (
        registry_path if registry_path is not None else os.environ.get(REGISTRY_ENV)
    )
    reg_policy = PathPolicy(
        owner_uids=registry_policy.owner_uids,
        check_ancestors=registry_policy.check_ancestors,
        allow_sticky_ancestors=registry_policy.allow_sticky_ancestors,
        forbidden_roots=(*registry_policy.forbidden_roots, *roots),
    )
    registry = load_trust_registry(
        chosen,
        policy=reg_policy,
        expected_registry_id=registry_id,
        min_serial=min_registry_serial,
    )
    if (
        not isinstance(expected_registry_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected_registry_sha256) is None
        or not hmac.compare_digest(registry.sha256, expected_registry_sha256)
    ):
        raise LinkRefused("operator_registry_sha256_mismatch")
    registry_dir = str(Path(chosen).parent) if chosen else ""
    ev_policy = PathPolicy(
        owner_uids=evidence_policy_.owner_uids,
        check_ancestors=evidence_policy_.check_ancestors,
        allow_sticky_ancestors=evidence_policy_.allow_sticky_ancestors,
        forbidden_roots=(*evidence_policy_.forbidden_roots, registry_dir),
    )
    reviews: dict[str, TrustedReview] = {}
    try:
        for stage in STAGES:
            entry = stages[stage]
            artifact = read_file(entry.artifact, ev_policy, ARTIFACT_MAX).data
            receipt = read_file(entry.receipt, ev_policy, RECEIPT_MAX).data
            reviews[stage] = verify_registry_review(
                receipt,
                registry=registry,
                ledger=ledger,
                expected_stage=stage,
                expected_producer=producer,
                expected_run_id=run_id,
                expected_binnacle_commit=binnacle_commit,
                expected_target_sha256=target_sha256,
                expected_evidence_sha256=entry.evidence_sha256,
                reviewed_artifact=artifact,
                now=now,
                consume=False,
            )
    except PathRefused as exc:
        raise LinkRefused(f"evidence_{exc}") from exc
    digests = [item.reviewed_artifact_sha256 for item in reviews.values()]
    if len(set(digests)) != len(digests):
        raise LinkRefused("cross_stage_artifact_reuse")
    try:
        ledger.record([item.replay_key for item in reviews.values()])
    except RegistryRefused as exc:
        raise LinkRefused(str(exc)) from exc
    return {
        "schema": "binnacle.p36.trust-link/1",
        "selection": "REWORK",
        "resource": "REWORK",
        "read": "NO-GO",
        "public_release": "NO-GO",
        "attestations_verified": False,
        "authority_granted": False,
        "os_confinement_accepted": False,
        "run_id": run_id,
        "replay_protection": "persistent_ledger" if ledger.persistent else "ephemeral",
        "registry": {
            "registry_id": registry_id,
            "serial": registry.doc.serial,
            "sha256": registry.sha256,
            "owner_is_current_user": registry.owner_is_current_user,
        },
        "stages": {
            stage: {
                "reviewer": item.reviewer,
                "key_id": item.key_id,
                "outcome": item.outcome,
                "artifact_sha256": item.reviewed_artifact_sha256,
                "signed_payload_sha256": item.signed_payload_sha256,
            }
            for stage, item in reviews.items()
        },
        "blockers": list(BLOCKERS),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=None)
    parser.add_argument("--registry-id", required=True)
    parser.add_argument("--min-registry-serial", type=int, required=True)
    parser.add_argument("--registry-sha256", required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--producer", required=True)
    parser.add_argument("--binnacle-commit", required=True)
    parser.add_argument("--target-sha256", required=True)
    for stage in STAGES:
        parser.add_argument(
            f"--{stage.lower().replace('.', '')}",
            nargs=3,
            metavar=("ARTIFACT", "EVIDENCE_SHA256", "RECEIPT"),
            required=True,
        )
    args = parser.parse_args(argv)
    # The CLI never accepts process-owned registries or shared ancestors.
    strict = PathPolicy(owner_uids=frozenset({0}))
    ledger_policy = PathPolicy(owner_uids=frozenset({os.geteuid()}))
    stages: dict[str, StageInput] = {
        stage: StageInput(*getattr(args, stage.lower().replace(".", "")))
        for stage in STAGES
    }
    try:
        result = link_stage_evidence(
            registry_path=args.registry,
            registry_policy=strict,
            evidence_policy_=evidence_policy(),
            ledger=FileReplayLedger(args.ledger, ledger_policy),
            registry_id=args.registry_id,
            min_registry_serial=args.min_registry_serial,
            expected_registry_sha256=args.registry_sha256,
            run_id=args.run_id,
            producer=args.producer,
            binnacle_commit=args.binnacle_commit,
            target_sha256=args.target_sha256,
            stages=stages,
        )
    except (LinkRefused, RegistryRefused, ReviewRefused) as exc:
        print(
            json.dumps(
                {
                    "schema": "binnacle.p36.trust-link/1",
                    "selection": "NO-GO",
                    "read": "NO-GO",
                    "public_release": "NO-GO",
                    "attestations_verified": False,
                    "reason": str(exc),
                },
                sort_keys=True,
            )
        )
        return 2
    except Exception:  # noqa: BLE001
        # Never disclose untrusted evidence or local paths in a traceback.
        print(
            json.dumps(
                {
                    "schema": "binnacle.p36.trust-link/1",
                    "selection": "NO-GO",
                    "read": "NO-GO",
                    "public_release": "NO-GO",
                    "attestations_verified": False,
                    "reason": "internal_error",
                },
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, sort_keys=True, indent=2))
    return 1  # A linkage report is never an authorizing exit 0.


if __name__ == "__main__":
    raise SystemExit(main())
