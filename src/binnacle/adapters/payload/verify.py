"""Payload-root startup verification helpers."""

from __future__ import annotations

from pathlib import Path


def find_orphan_payloads(directory: Path, known_relative_paths: frozenset[str]) -> tuple[Path, ...]:
    objects = directory / "objects"
    if not objects.exists():
        return ()
    return tuple(
        sorted(
            (
                path
                for path in objects.iterdir()
                if f"objects/{path.name}" not in known_relative_paths
            ),
            key=lambda item: item.name,
        )
    )
