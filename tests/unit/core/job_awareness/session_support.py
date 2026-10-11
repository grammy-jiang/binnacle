"""Shared synthetic E2 lab fixtures. Values are registered synthetic test data."""

import asyncio
import hashlib
import json
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from binnacle.features.commands.job_awareness.grants import TrustedClock
from binnacle.features.commands.job_awareness.session_lab import (
    LabConfig,
    LabError,
    SessionLab,
)
from binnacle.features.commands.job_awareness.session_route import (
    SESSION_META,
    SUBJECT_META,
    KeyDigest,
    RouteOutcome,
    route,
)
from binnacle.features.commands.job_awareness.session_snapshot import FrozenTemplate

RAW_VALUE = re.compile(rb"v1/[A-Za-z0-9_-]{40,}")
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
REGISTERED: set[str] = set()


def synthetic(tag: str, length: int) -> str:
    seed = hashlib.sha256(f"e2-lab-synthetic-{tag}".encode()).digest() * 4
    value = "v1/" + "".join(ALPHABET[b % 64] for b in seed[:length])
    REGISTERED.add(value)
    return value


def pair(name: str) -> tuple[str, str]:
    """(session, subject) of one synthetic chat; one subject per account."""
    return synthetic("session-" + name, 76), synthetic("subject-owner", 54)


def template_bytes(index: int, owner: str = "A") -> bytes:
    slot = f"R3-SYN-JOB-{index:02d}"
    body = {
        "contains_real_user_data": False,
        "job_id": slot,
        "nonce": hashlib.sha256(slot.encode()).hexdigest()[:32],
        "owner": owner,
        "records": [
            {"seq": seq, "value": f"synthetic-r3-{index:02d}-{seq:02d}"}
            for seq in range(3)
        ],
        "schema": "r3-synthetic-result-v1",
    }
    return (json.dumps(body, indent=2, sort_keys=True) + "\n").encode()


def template(index: int) -> FrozenTemplate:
    data = template_bytes(index)
    nonce = json.loads(data)["nonce"]
    return FrozenTemplate(
        f"R3-SYN-JOB-{index:02d}",
        data,
        hashlib.sha256(data).hexdigest(),
        hashlib.sha256(nonce.encode()).hexdigest(),
    )


TEMPLATES = {t.slot: t for t in (template(i) for i in range(1, 13))}


class ManualClock:
    def __init__(self, wall_ms: int = 1_800_000_000_000) -> None:
        self.wall_ms = wall_ms
        self.mono_ns = 10**12

    def advance(self, ms: int) -> None:
        self.wall_ms += ms
        self.mono_ns += ms * 1_000_000

    def trusted(self) -> TrustedClock:
        return TrustedClock(lambda: self.wall_ms, lambda: self.mono_ns)


@dataclass
class Lab:
    lab: SessionLab
    clock: ManualClock
    phase: Path
    events: list[dict[str, object]]
    faults: list[str]

    def outcome(self, name: str) -> RouteOutcome:
        session, subject = pair(name)
        meta = {SESSION_META: session, SUBJECT_META: subject}
        return route(self.lab.keyer, [session], [subject], meta)

    def key(self, name: str) -> KeyDigest:
        outcome = self.outcome(name)
        assert outcome.key is not None
        return outcome.key

    def start(self, name: str, slot: str) -> str | LabError:
        return asyncio.run(self.lab.start_fixture(self.outcome(name), slot))

    def rows(self, sql: str, params: tuple[object, ...] = ()) -> list[Any]:
        db = sqlite3.connect(self.lab.ledger.path)
        try:
            return db.execute(sql, params).fetchall()
        finally:
            db.close()


def make_lab(
    phase: Path,
    *,
    clock: ManualClock | None = None,
    config: LabConfig | None = None,
    fault: Callable[[str], None] | None = None,
    start: bool = True,
    **kwargs: Any,
) -> Lab:
    clock = clock or ManualClock()
    events: list[dict[str, object]] = []
    seen: list[str] = []

    def faults(point: str) -> None:
        seen.append(point)
        if fault is not None:
            fault(point)

    lab = SessionLab(
        phase,
        TEMPLATES,
        clock.trusted(),
        config=config,
        faults=faults,
        events=events.append,
        **kwargs,
    )
    if start:
        assert lab.start()
    return Lab(lab, clock, phase, events, seen)


def raw_scan(*blobs: bytes) -> list[bytes]:
    """Every raw-looking value; only exact registered synthetic values pass."""
    hits = []
    for blob in blobs:
        hits.extend(RAW_VALUE.findall(blob))
    return hits


def scan_phase(phase: Path, events: list[dict[str, object]]) -> list[bytes]:
    blobs = [p.read_bytes() for p in phase.rglob("*") if p.is_file()]
    blobs.append(repr(events).encode())
    return raw_scan(*blobs)
