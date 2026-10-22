"""Synthetic, test-only P3.6 trust-chain builders: ephemeral keys, temp roots.

No key here is persisted outside a pytest temporary directory, and none is a
real reviewer key. The operator and evidence roots are separate directories.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.lsp_p36_link import StageInput
from scripts.lsp_p36_secure_io import PathPolicy
from scripts.lsp_p36_signed_review import RegistryReviewReceipt, canonical_bytes_v2

NOW = datetime(2026, 10, 23, 7, 0, tzinfo=timezone.utc)
REGISTRY_ID = "synthetic-operator-registry"
RUN_ID = "synthetic-run-0001"
PRODUCER = "synthetic-ci-producer"
COMMIT = "a" * 40
TARGET = hashlib.sha256(b"synthetic-target").hexdigest()
STAGES = ("P3.3", "P3.4", "P3.5")


def process_owner_policy() -> PathPolicy:
    """Process-owned temp roots stand in for operator ownership in unit tests."""
    return PathPolicy(owner_uids=frozenset({os.geteuid()}), allow_sticky_ancestors=True)


def raw_public(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )


def key_entry(key: Ed25519PrivateKey, principal: str, **extra: Any) -> dict[str, Any]:
    pub = raw_public(key)
    entry: dict[str, Any] = {
        "key_id": hashlib.sha256(pub).hexdigest(),
        "public_key_b64": base64.b64encode(pub).decode(),
        "principal": principal,
        "stages": list(STAGES),
        "not_before_utc": "2026-01-01T00:00:00Z",
        "not_after_utc": "2027-01-01T00:00:00Z",
        "state": "active",
        "state_changed_at_utc": None,
        "supersedes": None,
    }
    entry.update(extra)
    return entry


def registry_doc(*entries: dict[str, Any], **extra: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "registry_schema": "binnacle.p36.trust-registry/1",
        "registry_id": REGISTRY_ID,
        "serial": 3,
        "issued_at_utc": "2026-10-01T00:00:00Z",
        "producer_principals": [PRODUCER],
        "keys": list(entries),
    }
    doc.update(extra)
    return doc


def write_private(path: Path, data: bytes, mode: int = 0o600) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    path.write_bytes(data)
    path.chmod(mode)
    return path


def write_registry(path: Path, doc: dict[str, Any]) -> Path:
    return write_private(path, json.dumps(doc).encode())


def sign_receipt(
    key: Ed25519PrivateKey,
    stage: str,
    artifact: bytes,
    evidence: str,
    **override: Any,
) -> bytes:
    """Sign a v2 receipt; ``override`` may replace any signed field."""
    fields: dict[str, Any] = {
        "receipt_schema": "binnacle.p36.review-ed25519/2",
        "stage": stage,
        "key_id": hashlib.sha256(raw_public(key)).hexdigest(),
        "registry_id": REGISTRY_ID,
        "run_id": RUN_ID,
        "reviewer": "independent-reviewer",
        "producer": PRODUCER,
        "binnacle_commit": COMMIT,
        "target_sha256": TARGET,
        "artifact_sha256": hashlib.sha256(artifact).hexdigest(),
        "evidence_sha256": evidence,
        "verdict": "GO",
        "issued_at_utc": "2026-10-23T06:59:00Z",
        "signature_b64": base64.b64encode(b"x" * 64).decode(),
    }
    fields.update(override)
    item = RegistryReviewReceipt(**fields)
    signature = key.sign(canonical_bytes_v2(item))
    final = item.model_copy(
        update={"signature_b64": base64.b64encode(signature).decode()}
    )
    return final.model_dump_json().encode()


@dataclass
class World:
    """Operator root, evidence root, state root, one external reviewer key."""

    root: Path
    reviewer: Ed25519PrivateKey = field(default_factory=Ed25519PrivateKey.generate)
    artifacts: dict[str, bytes] = field(default_factory=dict)

    @property
    def registry_path(self) -> Path:
        return self.root / "operator" / "registry.json"

    @property
    def ledger_path(self) -> Path:
        return self.root / "state" / "replay.ledger"

    def evidence_sha(self, stage: str) -> str:
        return hashlib.sha256(f"evidence-{stage}".encode()).hexdigest()

    def publish_registry(self, *entries: dict[str, Any], **extra: Any) -> Path:
        if not entries:
            entries = (key_entry(self.reviewer, "independent-reviewer"),)
        return write_registry(self.registry_path, registry_doc(*entries, **extra))

    def stage_inputs(self, **override: Any) -> dict[str, StageInput]:
        out: dict[str, StageInput] = {}
        for stage in STAGES:
            name = stage.replace(".", "")
            artifact = f'{{"synthetic":"{stage}"}}'.encode()
            self.artifacts[stage] = artifact
            art = write_private(self.root / "evidence" / f"{name}.json", artifact)
            rec = write_private(
                self.root / "evidence" / f"{name}.receipt",
                sign_receipt(
                    self.reviewer,
                    stage,
                    artifact,
                    self.evidence_sha(stage),
                    **override.get(stage, {}),
                ),
            )
            out[stage] = StageInput(str(art), self.evidence_sha(stage), str(rec))
        return out
