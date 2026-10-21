"""Binnacle-side workspace admission and LSP result validation.

Pure, provider-independent guards. The LSP adapters and JSON-RPC client live
exclusively in pinned multilspy; this module never imports or starts a provider.
This is a provisional security layer for the private P2.5 acceptance suite,
not proof of TOCTOU safety or OS-level process sandboxing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit


def _authorized_file(root: Path, relative: str) -> tuple[str, Path]:
    """Prevent implicit absolute, traversal, symlink and off-root file reads."""
    if not isinstance(relative, str) or not relative or "\x00" in relative:
        raise ValueError("invalid_pyright_source_path")
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("pyright_source_outside_workspace")
    candidate = (root / path).resolve(strict=True)
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise ValueError("pyright_source_outside_workspace")
    return str(candidate.relative_to(root)), candidate


def _result_location(root: Path, entry: Any) -> dict:
    """Normalize LSP Location and spec-valid LocationLink; fail off-root."""
    if not isinstance(entry, dict):
        raise TypeError("invalid_pyright_location")
    uri = entry.get("uri", entry.get("targetUri"))
    span = entry.get("range", entry.get("targetSelectionRange"))
    if not isinstance(uri, str) or not isinstance(span, dict):
        raise TypeError("invalid_pyright_location")
    for endpoint in ("start", "end"):
        position = span.get(endpoint)
        if not isinstance(position, dict) or any(
            type(position.get(field)) is not int or position[field] < 0
            for field in ("line", "character")
        ):
            raise ValueError("invalid_pyright_location_range")
    parsed = urlsplit(uri)
    if (
        parsed.scheme != "file"
        or parsed.netloc not in ("", "localhost")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("unsupported_pyright_result_uri")
    path = Path(unquote(parsed.path)).resolve(strict=False)
    if not path.is_relative_to(root):
        raise ValueError("pyright_result_outside_workspace")
    return {
        "uri": uri,
        "range": span,
        "absolutePath": str(path),
        "relativePath": str(path.relative_to(root)),
    }


def normalize_locations(root: Path, response: Any) -> list[dict]:
    """Treat null as zero results; support single or plural LocationLink."""
    if response is None:
        return []
    entries = response if isinstance(response, list) else [response]
    if len(entries) > 2048:
        raise ValueError("pyright_location_limit")
    return [_result_location(root, item) for item in entries]
