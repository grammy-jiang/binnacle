#!/usr/bin/env python3
"""Create a canonical manifest for an already-staged privileged-broker artifact."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from binnacle.privileged_broker.artifact import (
    PrivilegedArtifactError,
    PrivilegedArtifactVerificationSettings,
    write_privileged_artifact_manifest,
)

_PROTECTED_ROOTS = (
    Path("/etc"),
    Path("/opt"),
    Path("/run"),
    Path("/var"),
    Path("/srv/binnacle-runtime"),
)


def build_staging_manifest(root: Path) -> dict[str, object]:
    try:
        canonical = root.resolve(strict=True)
    except OSError as exc:
        raise PrivilegedArtifactError("privileged staging root is unavailable") from exc
    if any(
        canonical == protected or canonical.is_relative_to(protected)
        for protected in _PROTECTED_ROOTS
    ):
        raise PrivilegedArtifactError("privileged staging root overlaps protected host state")
    manifest = write_privileged_artifact_manifest(
        settings=PrivilegedArtifactVerificationSettings(
            root=canonical,
            expected_owner_uid=os.geteuid(),
            expected_owner_gid=os.getegid(),
            require_fixed_root=False,
        )
    )
    return {
        "build_sha256": manifest.build_sha256,
        "directory_count": len(manifest.directories),
        "file_count": len(manifest.files),
        "format_version": manifest.format_version,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", choices=("human", "json"), default="human")
    arguments = parser.parse_args(argv)
    try:
        result = build_staging_manifest(arguments.root)
    except (OSError, PrivilegedArtifactError) as exc:
        print(f"Privileged artifact manifest failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    if arguments.output == "json":
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    else:
        print(
            f"privileged artifact format={result['format_version']} "
            f"directories={result['directory_count']} files={result['file_count']} "
            f"build_sha256={result['build_sha256']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
