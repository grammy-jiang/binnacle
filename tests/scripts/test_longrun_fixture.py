"""Round 4 long-running fixture output-shape tests."""

from __future__ import annotations

import io
from typing import Any

import pytest

from scripts import longrun_fixture as fixture


class RecordingBytesIO(io.BytesIO):
    def __init__(self) -> None:
        super().__init__()
        self.writes: list[bytes] = []

    def write(self, data: Any) -> int:
        copied = bytes(data)
        self.writes.append(copied)
        return super().write(copied)


def no_sleep(_seconds: float) -> None:
    pass


def lines(stream: io.BytesIO) -> list[str]:
    return stream.getvalue().decode("utf-8").splitlines()


def assert_sequence(output: list[str], nonce: str, mode: str) -> None:
    assert len(output) > 0
    for seq, line in enumerate(output):
        assert f"fixture={nonce} seq={seq} mode={mode}" in line


def test_normal_has_numbered_lines_at_small_duration() -> None:
    stream = io.BytesIO()
    sleeps: list[float] = []
    assert fixture.normal(stream, "normal-nonce", 0.001, 0.02, sleeps.append) == 0
    output = lines(stream)
    assert len(output) == 3
    assert sum(sleeps) == pytest.approx(0.06)
    assert_sequence(output, "normal-nonce", "normal")


def test_high_has_bursts_and_a_line_larger_than_hard_cap() -> None:
    stream = io.BytesIO()
    assert fixture.high(stream, "high-nonce", 1, 0.001, no_sleep) == 0
    output = lines(stream)
    assert_sequence(output, "high-nonce", "high")
    assert len(output) == 3
    assert max(len(line) for line in output) > fixture.HARD_CAP_CHARS


def test_quiet_emits_only_one_line_after_delay() -> None:
    stream = io.BytesIO()
    sleeps: list[float] = []
    assert fixture.quiet(stream, "quiet-nonce", 0.001, sleeps.append) == 0
    assert sleeps == pytest.approx([0.06])
    output = lines(stream)
    assert_sequence(output, "quiet-nonce", "quiet")
    assert output[0].endswith("after_silence=true")


def test_fail_emits_one_line_and_returns_three() -> None:
    stream = io.BytesIO()
    sleeps: list[float] = []
    assert fixture.fail(stream, "fail-nonce", 0.01, sleeps.append) == 3
    assert sleeps == [0.01]
    output = lines(stream)
    assert_sequence(output, "fail-nonce", "fail")
    assert output[0].endswith("exit_code=3")


def test_utf8_splits_a_multibyte_character_between_writes() -> None:
    stream = RecordingBytesIO()
    sleeps: list[float] = []
    assert fixture.utf8(stream, "utf8-nonce", 2, 0.01, sleeps.append) == 0
    output = lines(stream)
    assert_sequence(output, "utf8-nonce", "utf8")
    assert all(f"text={fixture.UTF8_MARKER}" in line for line in output)
    assert sleeps == [0.01, 0.01]
    emoji = "🙂".encode()
    assert stream.writes[0].endswith(emoji[:-1])
    assert stream.writes[1].startswith(emoji[-1:])


def test_cancel_is_numbered_until_stopped_by_caller() -> None:
    stream = io.BytesIO()
    calls = 0

    def stop_after_two(_seconds: float) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        fixture.cancel(stream, "cancel-nonce", 0.01, stop_after_two)
    output = lines(stream)
    assert_sequence(output, "cancel-nonce", "cancel")
    assert len(output) == 2
