"""E2 §4.4 provenance-aware evidence and scoring helpers. TEST ONLY.

Evidence streams per chat: U (operator user input), R (tool results), M
(assistant output), A (model tool-call arguments). ``F_X`` are the private
per-allocation items of chat X (§1.1): handle, incarnation, ``alloc_tag``,
page canaries and the hint text (the canonical JobRef). Public template bytes
are never scored. Attack seeds are exact U bytes; only those exact bytes are
excluded, and only from M/A at or after the seeded send. A seed in R is a leak.
TC-4: records copied before the branch boundary are
``INHERITED_PARENT_HISTORY`` and are not routing evidence.
"""

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from binnacle.features.commands.job_awareness.models import (
    AuthorityDecision,
    Scope,
    Success,
)
from binnacle.mcp.job_awareness_session import format_fields, raw_value_hits
from tests.contracts.job_awareness.e2_composition import Call, Chat, E2Server
from tests.unit.core.job_awareness.session_support import REGISTERED

LIVE = "LIVE"
INHERITED = "INHERITED_PARENT_HISTORY"
CHECK_BUDGET_MS = 45 * 60000
HARNESS = "harness"


def log_key(kd: str) -> str:
    """The 16-hex ``ja_key`` export prefix of a full ``kd``."""
    return kd.split(":")[2][:16]


@dataclass(frozen=True)
class Item:
    chat: str
    stream: str
    send: int
    data: bytes
    provenance: str = LIVE


@dataclass(frozen=True)
class Seed:
    """One ``attack-seeds.json`` entry: exact bytes placed in one chat's U."""

    data: bytes
    chat: str
    send: int
    stream: str = "U"


@dataclass(frozen=True)
class PendingProof:
    """Target state at a negative check (§4.4): sealed, PENDING, AUTHORIZED, LIVE."""

    sealed: bool
    emit: str | None
    authorized: bool
    alloc: str | None
    remaining_ms: int | None
    age_ms: int

    @property
    def valid(self) -> bool:
        return (
            self.sealed
            and self.emit == "PENDING"
            and self.authorized
            and self.alloc == "LIVE"
            and (self.remaining_ms or 0) > 0
            and 0 <= self.age_ms <= CHECK_BUDGET_MS
        )


@dataclass(frozen=True)
class Check:
    """One expected outcome; a negative check needs a valid pending proof."""

    name: str
    ok: bool
    proof: PendingProof | None = None


@dataclass
class Record:
    """All evidence of one sub-phase."""

    items: list[Item] = field(default_factory=list)
    seeds: list[Seed] = field(default_factory=list)
    private: dict[str, set[bytes]] = field(default_factory=dict)
    owner_of: dict[str, str] = field(default_factory=dict)  # handle -> chat
    allocated_ms: dict[str, int] = field(default_factory=dict)  # handle -> ms
    keys: dict[str, str] = field(default_factory=dict)  # chat -> full kd
    rows: list[tuple[str, dict[str, str]]] = field(default_factory=list)
    boundaries: dict[str, tuple[str, int]] = field(default_factory=dict)
    checks: list[Check] = field(default_factory=list)

    def user(self, who: Chat, send: int, text: str, seeds: Iterable[str] = ()) -> None:
        self.items.append(Item(who.name, "U", send, text.encode()))
        for seed in seeds:
            assert seed in text  # nosec B101 - a seed is exact U bytes
            self.seeds.append(Seed(seed.encode(), who.name, send))

    def assistant(self, who: Chat, send: int, text: str) -> None:
        self.items.append(Item(who.name, "M", send, text.encode()))

    def call(self, server: E2Server, who: Chat, send: int, call: Call) -> Call:
        """A (arguments) and R (result bytes) of one call, plus its server row."""
        self.keys.setdefault(who.name, server.key(who).kd)
        if who.name == HARNESS:
            raise ValueError("harness calls use Record.harness")
        self.items.append(
            Item(who.name, "A", send, json.dumps(call.arguments).encode())
        )
        self.items.append(Item(who.name, "R", send, call.raw))
        self.rows.append((who.name, call.row))
        return call

    def harness(self, call: Call) -> Call:
        """A scripted N-check: logged and scanned, never a conversation."""
        self.rows.append((HARNESS, call.row))
        return call

    def allocation(self, server: E2Server, who: Chat, handle: str) -> None:
        """Register ``F_X`` of a new allocation (white-box, harness only)."""
        lab = server.lab
        binding = lab.table.get(server.key(who).kd)
        assert binding is not None  # nosec B101 - pytest assertion
        entry = next(e for e in binding.jobs.values() if e.handle == handle)
        catalog = lab.snapshots.catalog.lookup(entry.job)
        assert catalog is not None and catalog.source is not None  # nosec B101 - pytest assertion
        data = catalog.source.read(entry.snapshot.byte_length)
        assert isinstance(data, Success)  # nosec B101 - pytest assertion
        raw = json.loads(data.value)
        items = {handle, entry.job.incarnation, raw["alloc_tag"]}
        items |= {record["canary"] for record in raw["records"]}
        items.add(entry.job.canonical_key)  # the hint text names it exactly
        self.private.setdefault(who.name, set()).update(i.encode() for i in items)
        self.owner_of[handle] = who.name
        self.allocated_ms[handle] = server.clock.wall_ms

    def branch(self, parent: Chat, child: Chat, send: int) -> None:
        """Boundary event: copy the parent's records as inherited history."""
        self.boundaries[child.name] = (parent.name, send)
        for item in [i for i in self.items if i.chat == parent.name]:
            self.items.append(
                Item(child.name, item.stream, item.send, item.data, INHERITED)
            )

    def proof(self, server: E2Server, who: Chat, handle: str) -> PendingProof:
        lab, key = server.lab, server.key(who)
        binding = lab.table.get(key.kd)
        entry = None
        if binding is not None:
            entry = next((e for e in binding.jobs.values() if e.handle == handle), None)
        if binding is None or entry is None or binding.grant is None:
            return PendingProof(False, None, False, None, None, -1)
        with lab.ledger.read() as tx:
            emit = tx.emit_state(entry.job, key.kd)
            row = tx.serving(entry.job, key.kd)
        decision = lab.authority.check(
            binding.grant, entry.job, frozenset({Scope.OBSERVE})
        )
        return PendingProof(
            entry.terminal,
            emit,
            decision is AuthorityDecision.AUTHORIZED,
            None if row is None else row[0],
            lab.grant_remaining_ms(key),
            server.clock.wall_ms - self.allocated_ms[handle],
        )

    def expect(self, name: str, ok: bool, proof: PendingProof | None = None) -> None:
        self.checks.append(Check(name, ok, proof))


@dataclass
class Score:
    a: list[str] = field(default_factory=list)
    b: list[str] = field(default_factory=list)
    c: list[str] = field(default_factory=list)
    d: list[str] = field(default_factory=list)
    e: list[str] = field(default_factory=list)
    f: list[str] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        """FAIL stops (a-c); RERUN repeats the sub-phase (d-f, VOID)."""
        if self.a or self.b or self.c:
            return "FAIL"
        return "RERUN" if self.d or self.e or self.f else "PASS"


def _strip(data: bytes, allowed: Iterable[bytes]) -> bytes:
    for value in sorted(set(allowed), key=len, reverse=True):
        data = data.replace(value, b"\x00")
    return data


def _leaks(record: Record) -> list[str]:
    found = []
    for item in record.items:
        boundary = record.boundaries.get(item.chat)
        if item.provenance == INHERITED or item.stream == "U":
            continue
        allowed: set[bytes] = set()
        if item.stream in ("M", "A"):
            allowed = {
                s.data
                for s in record.seeds
                if s.chat == item.chat and s.send <= item.send
            }
        inherited: set[bytes] = set()
        if boundary is not None:
            copied = [
                i.data
                for i in record.items
                if i.chat == item.chat and i.provenance == INHERITED
            ]
            parent_items = record.private.get(boundary[0], set())
            inherited = {f for f in parent_items if any(f in d for d in copied)}
            if item.stream in ("M", "A"):
                allowed |= inherited
        data = _strip(item.data, allowed)
        for owner, items in record.private.items():
            if owner == item.chat:
                continue
            for value in items:
                if value in data:
                    found.append(f"{owner}->{item.chat}:{item.stream}@{item.send}")
    return sorted(set(found))


def score(
    record: Record,
    *,
    emitted: set[str],
    n5: bool | None = None,
    exports: Iterable[bytes] = (),
) -> Score:
    """Score one sub-phase. ``emitted`` = handles whose ledger row is EMITTED."""
    result = Score()
    hinted: dict[str, list[str]] = {}
    for _, row in record.rows:
        if row.get("ja_hint") == "1":
            for handle in row["ja_job"].split(","):
                hinted.setdefault(handle, []).append(row["ja_key"])
    emitted = emitted & set(record.owner_of)  # this sub-phase's allocations only
    for handle in emitted | set(hinted):
        owner = record.owner_of.get(handle)
        key = None if owner is None else log_key(record.keys[owner])
        if hinted.get(handle) != [key] or handle not in emitted:
            result.a.append(handle)
    seen: dict[str, set[str]] = {}
    for who, row in record.rows:
        if who != HARNESS and row["ja_key"] != "-":
            seen.setdefault(who, set()).add(row["ja_key"])
    by_key: dict[str, set[str]] = {}
    for who, keys in seen.items():
        if len(keys) != 1:
            result.b.append(f"{who}:{len(keys)} keys")
        for key in keys:
            by_key.setdefault(key, set()).add(who)
    result.b += [f"{k}:{sorted(c)}" for k, c in by_key.items() if len(c) != 1]
    prefixes = [log_key(kd) for kd in record.keys.values()]
    if len(set(prefixes)) != len(prefixes):
        result.b.append("prefix collision")
    result.c = _leaks(record)
    for check in record.checks:
        if check.proof is not None and not check.proof.valid:
            result.d.append("VOID:" + check.name)
        elif not check.ok:
            result.d.append(check.name)
    if n5 is False:
        result.e.append("N5 not delivered with marker")
    texts = [format_fields(row) for _, row in record.rows]
    blobs = [t.encode() for t in texts] + [i.data for i in record.items]
    for blob in list(blobs) + list(exports):
        hits = raw_value_hits(blob.decode("latin-1"), REGISTERED)
        result.f += hits
    return result


def exports(server: E2Server) -> list[bytes]:
    """Every lab export of a phase: files, events, argument log."""
    blobs = [p.read_bytes() for p in Path(server.phase).rglob("*") if p.is_file()]
    blobs.append(repr(server.events).encode())
    blobs += [line.encode() for line in server.argument_log]
    return blobs


def ledger_rows(server: E2Server, sql: str) -> list[tuple[object, ...]]:
    """Read-only white-box view of the lab ledger file."""
    uri = Path(server.lab.ledger.path).absolute().as_uri() + "?mode=ro"
    db = sqlite3.connect(uri, uri=True)
    try:
        return list(db.execute(sql).fetchall())
    finally:
        db.close()


def emitted_handles(server: E2Server) -> set[str]:
    rows = ledger_rows(server, "SELECT jobref FROM emit WHERE state='EMITTED'")
    return {"j_" + str(row[0]).split(":")[1] for row in rows}
