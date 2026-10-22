"""Offline P3.4/P3.5 byte and source-consistency check; never authorizes P3.6 GO.

This is a reproducibility bridge, NOT a trusted evidence importer. User-supplied
SHA pins do not authenticate reviewers or provenance. Outputs keep all P3.6
evidence stages null; neither provider execution nor network access occurs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from scripts.lsp_p36_evidence import EvidenceBundle
from scripts.lsp_p36_secure_io import PathPolicy, PathRefused, read_file

P34_SCRIPTS = (
    "lsp_p34_breadth.py",
    "lsp_p34_evidence.py",
    "lsp_p34_fixtures.py",
    "lsp_p34_wire.py",
)
P35_OPERATIONS = frozenset(
    (
        "manager_definition",
        "definition",
        "references",
        "hover",
        "document_symbols",
        "workspace_symbols",
    )
)
MAX_BYTES = 256 * 1024
UPSTREAM_SHA = "08ba0dbe60b6e0a3eff4796cb77ff5c0837bc892"
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class EvidenceRefused(ValueError):
    """A fixed non-sensitive reason, never an exception containing input data."""


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceRefused("duplicate_json_key")
        result[key] = value
    return result


def _load(path: Path, sha256: str) -> dict[str, Any]:
    """Read one vetted regular file: no symlinks, hardlinks or foreign owners."""
    if not path.is_absolute() or not HEX64.fullmatch(sha256):
        raise EvidenceRefused("invalid_input_reference")
    try:
        raw = read_file(
            path,
            PathPolicy(owner_uids=frozenset({os.geteuid(), 0}), check_ancestors=False),
            MAX_BYTES,
        ).data
    except PathRefused as exc:
        raise EvidenceRefused(f"unreadable_evidence_file:{exc}") from exc
    if hashlib.sha256(raw).hexdigest() != sha256:
        raise EvidenceRefused("evidence_sha256_mismatch")
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_unique,
            parse_constant=lambda _: (_ for _ in ()).throw(
                EvidenceRefused("invalid_json_number")
            ),
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise EvidenceRefused("invalid_evidence_json") from exc
    if not isinstance(value, dict):
        raise EvidenceRefused("invalid_evidence_schema")
    return value


def _require(test: bool, message: str) -> None:
    if not test:
        raise EvidenceRefused(message)


def _p34(record: dict[str, Any], repo: Path) -> dict[str, Any]:
    _require(record.get("schema") == 1, "p34_schema_unrecognized")
    hashes = record.get("script_sha256")
    if not isinstance(hashes, dict) or set(hashes) != set(P34_SCRIPTS):
        raise EvidenceRefused("p34_script_inventory_mismatch")
    for name in P34_SCRIPTS:
        path = repo / "scripts" / name
        _require(
            path.is_file()
            and not path.is_symlink()
            and hashes[name] == hashlib.sha256(path.read_bytes()).hexdigest(),
            "p34_script_identity_mismatch",
        )
    rows = record.get("providers")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 20:
        raise EvidenceRefused("p34_rows_invalid")
    names: set[str] = set()
    statuses: dict[str, int] = dict.fromkeys(("pass", "not_installed", "failed"), 0)
    for row in rows:
        if not isinstance(row, dict):
            raise EvidenceRefused("p34_row_invalid")
        provider_name = row.get("provider")
        if (
            not isinstance(provider_name, str)
            or not provider_name
            or provider_name in names
        ):
            raise EvidenceRefused("p34_duplicate_provider")
        names.add(provider_name)
        status = row.get("status")
        if not isinstance(status, str):
            raise EvidenceRefused("p34_status_invalid")
        if status == "pass":
            _require(
                row.get("initialize") == "pass"
                and row.get("shutdown") == "pass"
                and row.get("exit") == "pass"
                and row.get("document_symbol") == "fixture_pass"
                and row.get("fixture_files_unchanged") is True
                and row.get("extra_workspace_entries") == 0
                and row.get("cleanup") == "group_signaled_leader_reaped",
                "p34_positive_without_gold_or_integrity",
            )
        statuses[status] = statuses.get(status, 0) + 1
    return {
        "provider_count": len(rows),
        "status_counts": statuses,
        "pyright_in_native_probe": "pyright" in names,
        "script_digests_match_local_source": True,
    }


def _harness_sha(repo: Path) -> str:
    digest = hashlib.sha256()
    files = sorted((repo / "scripts" / "lsp_benchmark").glob("*.py"))
    _require(bool(files), "p35_harness_missing")
    for file in files:
        _require(file.is_file() and not file.is_symlink(), "p35_harness_invalid")
        digest.update(file.name.encode())
        digest.update(file.read_bytes())
    return digest.hexdigest()


def _p35(record: dict[str, Any], repo: Path) -> dict[str, Any]:
    _require(record.get("schema") == "binnacle.p35/1", "p35_schema_unrecognized")
    env = record.get("environment")
    if not isinstance(env, dict):
        raise EvidenceRefused("p35_environment_invalid")
    _require(
        env.get("harness_sha256") == _harness_sha(repo)
        and env.get("uv_lock_sha256")
        == hashlib.sha256((repo / "uv.lock").read_bytes()).hexdigest(),
        "p35_source_identity_mismatch",
    )
    provider = record.get("provider")
    if not isinstance(provider, dict):
        raise EvidenceRefused("p35_provider_identity_mismatch")
    _require(
        provider.get("provider") == "pyright"
        and provider.get("multilspy_commit") == UPSTREAM_SHA,
        "p35_provider_identity_mismatch",
    )
    corpus, options = record.get("corpus"), record.get("options")
    if not isinstance(corpus, dict) or not isinstance(options, dict):
        raise EvidenceRefused("p35_corpus_invalid")
    _require(
        corpus.get("kind")
        in ("synthetic_small", "synthetic_medium", "trusted_real_snapshot"),
        "p35_corpus_kind_unrecognized",
    )
    count = options.get("instances")
    if type(count) is not int or not 1 <= count <= 8:
        raise EvidenceRefused("p35_instances_invalid")
    resource = record.get("resources")
    if not isinstance(resource, dict):
        raise EvidenceRefused("p35_resources_invalid")
    peak = resource.get("tree_rss_peak_bytes")
    if type(peak) is not int or peak <= 0:
        raise EvidenceRefused("p35_validity_claim_incomplete")
    _require(
        record.get("status") == "completed"
        and record.get("valid") is True
        and record.get("cleanup_verified") is True
        and record.get("snapshot_unchanged") is True
        and record.get("resident_reuse_verified") is True
        and record.get("authoritative_timings") is False
        and record.get("release_decision") == "NOT_EVALUATED_READ_NO_GO"
        and provider.get("read_release") == "NO_GO"
        and resource.get("status") == "observed"
        and resource.get("sampling_errors") == 0
        and type(peak) is int
        and peak > 0,
        "p35_validity_claim_incomplete",
    )
    operations = record.get("operations")
    if not isinstance(operations, list) or not 1 <= len(operations) <= 6:
        raise EvidenceRefused("p35_operation_inventory_invalid")
    names = set()
    total = 0
    for operation in operations:
        if not isinstance(operation, dict):
            raise EvidenceRefused("p35_operation_invalid")
        name = operation.get("operation")
        _require(
            name in P35_OPERATIONS and name not in names,
            "p35_operation_name_invalid",
        )
        names.add(name)
        warm = operation.get("warm")
        if not isinstance(warm, dict):
            raise EvidenceRefused("p35_warm_invalid")
        samples = warm.get("samples")
        if type(samples) is not int or samples <= 0:
            raise EvidenceRefused("p35_reported_gold_incomplete")
        _require(
            warm.get("correct") == samples
            and warm.get("incorrect") == 0
            and warm.get("error") == 0
            and warm.get("timeout") == 0
            and operation.get("supported_instances") == count,
            "p35_reported_gold_incomplete",
        )
        total += samples
    return {
        "provider": "pyright",
        "source_harness_digests_match_local_source": True,
        "corpus_kind": corpus["kind"],
        "reported_valid": True,
        "reported_gold_calls": total,
        "operation_count": len(operations),
        "resident_instances": count,
        "observed_peak_rss_mib": round(peak / 1048576, 2),
        "authoritative_timings": False,
    }


def inspect(
    *, p34: Path, p34_sha256: str, p35: Path, p35_sha256: str
) -> dict[str, Any]:
    """Verify local byte/source consistency, never certify independent review."""
    repo = Path(__file__).resolve().parents[1]
    raw34 = _load(p34, p34_sha256)
    raw35 = _load(p35, p35_sha256)
    checks34 = _p34(raw34, repo)
    checks35 = _p35(raw35, repo)
    pending = EvidenceBundle(schema_version=1)
    return {
        "schema": "binnacle.p36.import-rework/1",
        "selection": "REWORK",
        "resource": "REWORK",
        "read": "NO-GO",
        "public_release": "NO-GO",
        "attestations_verified": False,
        "p3_6_bundle": pending.model_dump(mode="json"),
        "inputs": {
            "p34": {"sha256": p34_sha256, **checks34},
            "p35": {"sha256": p35_sha256, **checks35},
        },
        "blockers": [
            "p33_os_confinement_and_signed_safety_unverified",
            "p34_pyright_method_identity_unverified",
            "p35_raw_events_and_gold_not_independently_attested",
            "p35_idle_cpu_soak_and_eviction_unverified",
            "p36_cross_stage_evidence_identity_unbound",
            "p36_reviewer_authentication_missing",
        ],
        "trust_note": (
            "Operator-supplied SHA pins and producer JSON are not independent "
            "attestations. Reviewer authentication and stage linking are a "
            "separate step: scripts/lsp_p36_link.py with an operator registry."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for stage in ("p34", "p35"):
        parser.add_argument(f"--{stage}", required=True, type=Path)
        parser.add_argument(f"--{stage}-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        result = inspect(
            p34=args.p34,
            p34_sha256=args.p34_sha256,
            p35=args.p35,
            p35_sha256=args.p35_sha256,
        )
    except (EvidenceRefused, OSError, ValueError, TypeError) as exc:
        reason = str(exc) if isinstance(exc, EvidenceRefused) else "malformed_input"
        print(
            json.dumps(
                {
                    "schema": "binnacle.p36.import-rework/1",
                    "selection": "NO-GO",
                    "read": "NO-GO",
                    "public_release": "NO-GO",
                    "attestations_verified": False,
                    "reason": reason,
                },
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, sort_keys=True, indent=2))
    return 1  # Even valid local evidence may NEVER produce an authorizing exit 0.


if __name__ == "__main__":
    raise SystemExit(main())
