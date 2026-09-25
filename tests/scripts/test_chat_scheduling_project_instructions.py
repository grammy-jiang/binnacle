from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

import pytest

from scripts import chat_scheduling_project_instructions as project_instructions

CANONICAL_BLOCK = (
    Path(__file__).resolve().parents[2] / ".claude/skills/chatgpt-mcp-dev/references/"
    "project-instructions-chat-scheduling-v2.txt"
)


def _block(text: str = "synthetic scheduling\n") -> str:
    return (
        f"{project_instructions.BEGIN_MARKER}\n{text}{project_instructions.END_MARKER}"
    )


def test_frozen_canonical_block_sha_matches_repository_file():
    data = CANONICAL_BLOCK.read_bytes()
    assert hashlib.sha256(data).hexdigest() == (
        project_instructions.FROZEN_CANONICAL_BLOCK_SHA256
    )


def test_empty_instructions_append_two_newlines_and_one_complete_block():
    block = "synthetic scheduling\n"
    merged = project_instructions.merge_instructions("", block)
    assert merged == f"\n\n{_block(block)}"
    project_instructions.verify_instructions("", block, merged)


def test_existing_instructions_are_preserved_exactly_before_new_block():
    original = "Project-specific rules\nKeep this text byte-for-byte."
    block = "synthetic scheduling\n"
    merged = project_instructions.merge_instructions(original, block)
    assert merged == f"{original}\n\n{_block(block)}"
    project_instructions.verify_instructions(original, block, merged)


def test_existing_block_update_preserves_prefix_and_suffix_only():
    original = (
        "prefix α\r\n"
        f"{project_instructions.BEGIN_MARKER}\r\n"
        "old scheduling\r\n"
        f"{project_instructions.END_MARKER}\r\n"
        "suffix β\r\n"
    )
    block = "new scheduling\nsecond line\n"
    merged = project_instructions.merge_instructions(original, block)
    assert merged == (f"prefix α\r\n{_block(block)}\r\nsuffix β\r\n")
    project_instructions.verify_instructions(original, block, merged)


@pytest.mark.parametrize(
    "original",
    [
        f"prefix\n{project_instructions.BEGIN_MARKER}\nmissing end\n",
        f"prefix\n{project_instructions.END_MARKER}\nmissing begin\n",
        (f"{project_instructions.END_MARKER}\n{project_instructions.BEGIN_MARKER}\n"),
        (
            f"prefix {project_instructions.BEGIN_MARKER}\ntext\n"
            f"{project_instructions.END_MARKER}\n"
        ),
        (
            f"{project_instructions.BEGIN_MARKER}\ntext\n"
            f"{project_instructions.END_MARKER} suffix"
        ),
    ],
)
def test_malformed_markers_are_refused(original):
    with pytest.raises(project_instructions.InstructionFormatError):
        project_instructions.merge_instructions(original, "synthetic scheduling\n")


def test_duplicate_or_nested_blocks_are_refused():
    duplicate = f"{_block()}\n{_block()}"
    nested = (
        f"{project_instructions.BEGIN_MARKER}\n"
        f"{project_instructions.BEGIN_MARKER}\n"
        "nested\n"
        f"{project_instructions.END_MARKER}\n"
        f"{project_instructions.END_MARKER}"
    )
    for original in (duplicate, nested):
        with pytest.raises(
            project_instructions.InstructionFormatError,
            match="exactly one begin/end pair",
        ):
            project_instructions.merge_instructions(original, "synthetic scheduling\n")


def test_unicode_and_mixed_newlines_outside_existing_block_are_unchanged():
    prefix = "規則:\r\n- café\r\n"
    suffix = "\r\n尾部 Ω\r\n"
    old_block = _block("old\n")
    original = f"{prefix}{old_block}{suffix}"
    block = "新しい scheduling\nline two\n"
    merged = project_instructions.merge_instructions(original, block)
    assert merged[: len(prefix)] == prefix
    assert merged[-len(suffix) :] == suffix
    assert merged == f"{prefix}{_block(block)}{suffix}"
    project_instructions.verify_instructions(original, block, merged)


def test_verify_rejects_non_block_change_and_noncanonical_block():
    block = "canonical synthetic\n"
    original = "prefix\n"
    merged = project_instructions.merge_instructions(original, block)

    with pytest.raises(
        project_instructions.InstructionFormatError,
        match="non-scheduling text changed",
    ):
        project_instructions.verify_instructions(
            original, block, merged.replace("prefix", "changed", 1)
        )

    with pytest.raises(
        project_instructions.InstructionFormatError,
        match="does not match the canonical block",
    ):
        project_instructions.verify_instructions(
            original, block, merged.replace("canonical synthetic", "tampered", 1)
        )


def test_cli_merge_preserves_exact_snapshot_hash_and_writes_mode_0600(tmp_path, capsys):
    original = tmp_path / "original.txt"
    output = tmp_path / "merged.txt"
    original_bytes = "π\r\nrollback snapshot\r\n".encode()
    original.write_bytes(original_bytes)

    assert (
        project_instructions.main(
            [
                "merge",
                "--original",
                str(original),
                "--block",
                str(CANONICAL_BLOCK),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    canonical = CANONICAL_BLOCK.read_text(encoding="utf-8")
    expected = project_instructions.merge_instructions(
        original_bytes.decode(), canonical
    ).encode()
    assert report == {
        "block_sha256": project_instructions.FROZEN_CANONICAL_BLOCK_SHA256,
        "original_sha256": hashlib.sha256(original_bytes).hexdigest(),
        "output_sha256": hashlib.sha256(expected).hexdigest(),
    }
    assert output.read_bytes() == expected
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


def test_cli_verify_accepts_exact_readback_and_rejects_changed_readback(
    tmp_path, capsys
):
    original = tmp_path / "original.txt"
    actual = tmp_path / "actual.txt"
    original.write_text("project rules\n", encoding="utf-8", newline="")
    canonical = CANONICAL_BLOCK.read_text(encoding="utf-8")
    actual.write_text(
        project_instructions.merge_instructions("project rules\n", canonical),
        encoding="utf-8",
        newline="",
    )

    args = [
        "verify",
        "--original",
        str(original),
        "--block",
        str(CANONICAL_BLOCK),
        "--actual",
        str(actual),
    ]
    assert project_instructions.main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["verified"] is True
    assert report["block_sha256"] == (
        project_instructions.FROZEN_CANONICAL_BLOCK_SHA256
    )

    actual.write_text(
        actual.read_text(encoding="utf-8").replace("project rules", "changed rules"),
        encoding="utf-8",
        newline="",
    )
    assert project_instructions.main(args) == 1
    assert "non-scheduling text changed" in capsys.readouterr().out
