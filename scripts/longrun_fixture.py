"""Deterministic output fixture for Round 4 long-running job tests.

Run through ``run_command`` as, for example::

    .venv/bin/python scripts/longrun_fixture.py normal --nonce r4-a --n 10 --s 5

``N`` is mode-specific: minutes for normal/quiet, seconds for fail, and a
count for high/utf8. ``S`` is the pause between normal/cancel lines, high
bursts, and the deliberately split UTF-8 writes.
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from collections.abc import Callable
from typing import BinaryIO

HARD_CAP_CHARS = 24_000
HIGH_LINE_CHARS = HARD_CAP_CHARS + 1
UTF8_MARKER = "漢🙂é"
Sleep = Callable[[float], None]


def _line(nonce: str, seq: int, mode: str, detail: str = "") -> bytes:
    suffix = f" {detail}" if detail else ""
    return f"fixture={nonce} seq={seq} mode={mode}{suffix}\n".encode()


def _write(stream: BinaryIO, data: bytes) -> None:
    stream.write(data)
    stream.flush()


def normal(
    stream: BinaryIO, nonce: str, minutes: float, interval_s: float, sleep: Sleep
) -> int:
    duration_s = minutes * 60
    count = max(1, math.ceil(duration_s / interval_s))
    for seq in range(count):
        _write(stream, _line(nonce, seq, "normal"))
        elapsed_s = seq * interval_s
        sleep(min(interval_s, duration_s - elapsed_s))
    return 0


def high(
    stream: BinaryIO, nonce: str, bursts: int, interval_s: float, sleep: Sleep
) -> int:
    sizes = (4_096, 8_192, HIGH_LINE_CHARS)
    seq = 0
    for burst in range(bursts):
        for size in sizes:
            prefix = _line(nonce, seq, "high", f"burst={burst} chars={size}").rstrip(
                b"\n"
            )
            padding = b"x" * max(0, size - len(prefix))
            _write(stream, prefix + padding + b"\n")
            seq += 1
        if burst + 1 < bursts:
            sleep(interval_s)
    return 0


def quiet(stream: BinaryIO, nonce: str, minutes: float, sleep: Sleep) -> int:
    sleep(minutes * 60)
    _write(stream, _line(nonce, 0, "quiet", "after_silence=true"))
    return 0


def fail(stream: BinaryIO, nonce: str, delay_s: float, sleep: Sleep) -> int:
    sleep(delay_s)
    _write(stream, _line(nonce, 0, "fail", "exit_code=3"))
    return 3


def utf8(stream: BinaryIO, nonce: str, count: int, pause_s: float, sleep: Sleep) -> int:
    emoji = "🙂".encode()
    split = len(emoji) - 1
    for seq in range(count):
        prefix = f"fixture={nonce} seq={seq} mode=utf8 text=漢".encode()
        # End one physical write inside the four-byte emoji, pause, then finish
        # the same logical line. This exercises pending UTF-8 suffix handling.
        _write(stream, prefix + emoji[:split])
        sleep(pause_s)
        _write(stream, emoji[split:] + "é".encode() + b"\n")
    return 0


def cancel(stream: BinaryIO, nonce: str, interval_s: float, sleep: Sleep) -> int:
    seq = 0
    while True:
        _write(stream, _line(nonce, seq, "cancel"))
        seq += 1
        sleep(interval_s)


def _positive(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be > 0")
    return parsed


def _count(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be > 0")
    return parsed


def parser() -> argparse.ArgumentParser:
    out = argparse.ArgumentParser(description=__doc__)
    sub = out.add_subparsers(dest="mode", required=True)

    for mode in ("normal", "quiet"):
        p = sub.add_parser(mode)
        p.add_argument("--nonce", required=True)
        p.add_argument("--n", type=_positive, required=True, help="duration in minutes")
        if mode == "normal":
            p.add_argument(
                "--s", type=_positive, required=True, help="line interval seconds"
            )

    p = sub.add_parser("fail")
    p.add_argument("--nonce", required=True)
    p.add_argument("--n", type=_positive, required=True, help="delay in seconds")

    for mode in ("high", "utf8"):
        p = sub.add_parser(mode)
        p.add_argument("--nonce", required=True)
        p.add_argument("--n", type=_count, required=True, help="burst/line count")
        p.add_argument("--s", type=_positive, required=True, help="pause seconds")

    p = sub.add_parser("cancel")
    p.add_argument("--nonce", required=True)
    p.add_argument("--s", type=_positive, required=True, help="line interval seconds")
    return out


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    stream = sys.stdout.buffer
    if args.mode == "normal":
        return normal(stream, args.nonce, args.n, args.s, time.sleep)
    if args.mode == "high":
        return high(stream, args.nonce, args.n, args.s, time.sleep)
    if args.mode == "quiet":
        return quiet(stream, args.nonce, args.n, time.sleep)
    if args.mode == "fail":
        return fail(stream, args.nonce, args.n, time.sleep)
    if args.mode == "utf8":
        return utf8(stream, args.nonce, args.n, args.s, time.sleep)
    return cancel(stream, args.nonce, args.s, time.sleep)


if __name__ == "__main__":
    raise SystemExit(main())
