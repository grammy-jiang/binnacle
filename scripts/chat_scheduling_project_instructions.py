"""Merge and verify the canonical scheduling-v2 Project instruction block."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

BEGIN_MARKER = "=== BEGIN BINNACLE CHAT SCHEDULING V2 ==="
END_MARKER = "=== END BINNACLE CHAT SCHEDULING V2 ==="
FROZEN_CANONICAL_BLOCK_SHA256 = (
    "b7df6953a3c64bd245b3d5ff13b6f2667e940d5a154e650fec0b10e6a22cf094"
)


class InstructionFormatError(ValueError):
    """Raised when scheduling markers or readback violate the merge contract."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _decode_utf8(data: bytes, path: Path) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InstructionFormatError(f"{path}: expected UTF-8 text") from exc


def _read_text_and_sha(path: Path) -> tuple[str, str]:
    data = path.read_bytes()
    return _decode_utf8(data, path), sha256_bytes(data)


def _load_frozen_block(path: Path) -> tuple[str, str]:
    text, digest = _read_text_and_sha(path)
    if digest != FROZEN_CANONICAL_BLOCK_SHA256:
        raise InstructionFormatError(
            "canonical scheduling block SHA mismatch: "
            f"expected {FROZEN_CANONICAL_BLOCK_SHA256}, got {digest}"
        )
    if not text.endswith("\n"):
        raise InstructionFormatError(
            "canonical scheduling block must end with a newline"
        )
    return text, digest


def _marker_span(text: str, *, require_block: bool = False) -> tuple[int, int] | None:
    begin_count = text.count(BEGIN_MARKER)
    end_count = text.count(END_MARKER)
    if begin_count == 0 and end_count == 0:
        if require_block:
            raise InstructionFormatError("scheduling block is missing")
        return None
    if begin_count != 1 or end_count != 1:
        raise InstructionFormatError(
            "scheduling markers must contain exactly one begin/end pair "
            f"(begin={begin_count}, end={end_count})"
        )

    begin = text.index(BEGIN_MARKER)
    end = text.index(END_MARKER)
    if end <= begin:
        raise InstructionFormatError("scheduling end marker precedes begin marker")

    begin_after = begin + len(BEGIN_MARKER)
    end_after = end + len(END_MARKER)
    if begin > 0 and text[begin - 1] != "\n":
        raise InstructionFormatError("scheduling begin marker is not on its own line")
    if not (text.startswith("\n", begin_after) or text.startswith("\r\n", begin_after)):
        raise InstructionFormatError("scheduling begin marker is not on its own line")
    if end == 0 or text[end - 1] != "\n":
        raise InstructionFormatError("scheduling end marker is not on its own line")
    if end_after < len(text) and text[end_after] not in "\r\n":
        raise InstructionFormatError("scheduling end marker is not on its own line")
    return begin, end_after


def _render_block(block: str) -> str:
    if not block.endswith("\n"):
        raise InstructionFormatError("scheduling block text must end with a newline")
    return f"{BEGIN_MARKER}\n{block}{END_MARKER}"


def merge_instructions(original: str, block: str) -> str:
    """Return the deterministic scheduling-block merge for one Project."""
    rendered = _render_block(block)
    span = _marker_span(original)
    if span is None:
        return f"{original}\n\n{rendered}"
    begin, end = span
    return f"{original[:begin]}{rendered}{original[end:]}"


def verify_instructions(original: str, block: str, actual: str) -> None:
    """Verify exact non-block preservation and one canonical scheduling block."""
    span = _marker_span(actual, require_block=True)
    if span is None:  # pragma: no cover - require_block guarantees this
        raise InstructionFormatError("scheduling block is missing")
    begin, end = span
    if actual[begin:end] != _render_block(block):
        raise InstructionFormatError(
            "readback scheduling block does not match the canonical block"
        )
    expected = merge_instructions(original, block)
    if actual != expected:
        raise InstructionFormatError(
            "readback differs from deterministic merge; non-scheduling text changed"
        )


def _write_private_text(path: Path, text: str) -> str:
    data = text.encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(fd)
    return sha256_bytes(data)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    merge = subparsers.add_parser("merge")
    merge.add_argument("--original", type=Path, required=True)
    merge.add_argument("--block", type=Path, required=True)
    merge.add_argument("--output", type=Path, required=True)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--original", type=Path, required=True)
    verify.add_argument("--block", type=Path, required=True)
    verify.add_argument("--actual", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result: dict[str, object]
    try:
        original, original_sha = _read_text_and_sha(args.original)
        block, block_sha = _load_frozen_block(args.block)
        if args.command == "merge":
            merged = merge_instructions(original, block)
            output_sha = _write_private_text(args.output, merged)
            result = {
                "block_sha256": block_sha,
                "original_sha256": original_sha,
                "output_sha256": output_sha,
            }
        else:
            actual, actual_sha = _read_text_and_sha(args.actual)
            verify_instructions(original, block, actual)
            result = {
                "actual_sha256": actual_sha,
                "block_sha256": block_sha,
                "original_sha256": original_sha,
                "verified": True,
            }
    except (InstructionFormatError, OSError) as exc:
        print(f"error: {exc}")
        return 1

    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
