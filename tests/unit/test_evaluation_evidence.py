"""Write-once evidence storage and inventory validation tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from binnacle.evaluation.evidence import EvidenceStore, validate_evidence_inventory
from binnacle.evaluation.redaction import RedactionViolation


def test_evidence_store_writes_bounded_payload_and_revalidates_inventory(
    tmp_path: Path,
) -> None:
    store = EvidenceStore(tmp_path)
    record = store.add_bytes(
        evidence_id="phase3-scope",
        relative_path="phase3-capability-scope.json",
        data=b'{"catalogue":"compatibility-core"}\n',
        media_type="application/json",
        information_class="normal-result",
    )

    assert (tmp_path / record.path).stat().st_mode & 0o777 == 0o600
    assert validate_evidence_inventory(tmp_path, [record.as_manifest_value()]) == (record,)
    with pytest.raises(FileExistsError):
        store.add_bytes(
            evidence_id="other-id",
            relative_path="phase3-capability-scope.json",
            data=b"{}\n",
            media_type="application/json",
            information_class="normal-result",
        )


@pytest.mark.parametrize("path", ["../escape.json", "/absolute.json", ".hidden"])
def test_evidence_path_cannot_escape_or_hide(path: str, tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path)

    with pytest.raises(ValueError, match="unsafe"):
        store.add_bytes(
            evidence_id="safe-id",
            relative_path=path,
            data=b"{}\n",
            media_type="application/json",
            information_class="normal-result",
        )


def test_evidence_store_rejects_secret_bearing_payload(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path)

    with pytest.raises(RedactionViolation):
        store.add_bytes(
            evidence_id="unsafe-id",
            relative_path="unsafe.txt",
            data=b"Authorization: Bearer secret-token-value",
            media_type="text/plain",
            information_class="restricted-result",
        )


def test_inventory_detects_payload_changed_after_recording(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path)
    record = store.add_bytes(
        evidence_id="phase3-scope",
        relative_path="scope.json",
        data=b"{}\n",
        media_type="application/json",
        information_class="normal-result",
    )
    (tmp_path / record.path).write_bytes(b'{"changed":true}\n')

    with pytest.raises(ValueError, match="digest mismatch"):
        validate_evidence_inventory(tmp_path, [record.as_manifest_value()])


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"evidence_id": None}, "evidence_id is missing"),
        ({"path": "outside/file.json"}, "under evidence"),
        ({"sha256": "short"}, "digest is invalid"),
        ({"media_type": None}, "metadata is invalid"),
        ({"information_class": "secret"}, "not marked redacted"),
        ({"redacted": False}, "not marked redacted"),
        ({"path": "evidence/missing.json"}, "missing or not a regular file"),
    ],
)
def test_inventory_rejects_malformed_or_unresolved_metadata(
    tmp_path: Path,
    change: dict[str, object],
    message: str,
) -> None:
    record = (
        EvidenceStore(tmp_path)
        .add_bytes(
            evidence_id="fixture-evidence",
            relative_path="fixture.json",
            data=b"{}\n",
            media_type="application/json",
            information_class="normal-result",
        )
        .as_manifest_value()
    )
    record.update(change)

    with pytest.raises(ValueError, match=message):
        validate_evidence_inventory(tmp_path, [record])


def test_inventory_rejects_duplicate_identity_or_path(tmp_path: Path) -> None:
    record = (
        EvidenceStore(tmp_path)
        .add_bytes(
            evidence_id="fixture-evidence",
            relative_path="fixture.json",
            data=b"{}\n",
            media_type="application/json",
            information_class="normal-result",
        )
        .as_manifest_value()
    )

    with pytest.raises(ValueError, match="duplicate"):
        validate_evidence_inventory(tmp_path, [record, record])


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("evidence_id", "bad id", "canonical identifier"),
        ("information_class", "secret", "information class"),
        ("media_type", "", "media type"),
    ],
)
def test_store_rejects_invalid_manifest_metadata(
    tmp_path: Path,
    field: str,
    value: str,
    message: str,
) -> None:
    arguments: dict[str, Any] = {
        "evidence_id": "fixture-evidence",
        "relative_path": "fixture.json",
        "data": b"{}\n",
        "media_type": "application/json",
        "information_class": "normal-result",
    }
    arguments[field] = value

    with pytest.raises(ValueError, match=message):
        EvidenceStore(tmp_path).add_bytes(**arguments)


def test_evidence_subdirectory_symbolic_link_cannot_escape_workspace(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (store.evidence_root / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="parent path is unsafe"):
        store.add_bytes(
            evidence_id="fixture-evidence",
            relative_path="linked/fixture.json",
            data=b"{}\n",
            media_type="application/json",
            information_class="normal-result",
        )
    assert not (outside / "fixture.json").exists()
