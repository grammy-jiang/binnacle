"""E2 g5 §9.2 selector extension: the canonical key the reminder prints.

The lab selector grammar also accepts ``ja1_<32 hex>:<12 hex>:g1_<32 hex>``.
It resolves by exact match inside the caller key's own allocations only, as
a hard gate before any global read. Foreign, guessed, malformed and retired
keys return the same ``DENIED`` as every other failing selector.
"""

import asyncio
import re

from binnacle.features.commands.job_awareness import session_serving as serving
from binnacle.features.commands.job_awareness.session_lab import LabError
from binnacle.features.commands.job_awareness.session_route import (
    RouteOutcome,
    RouteStatus,
)
from tests.unit.core.job_awareness.session_support import make_lab

VALUES_1 = ["synthetic-r3-01-00", "synthetic-r3-01-01", "synthetic-r3-01-02"]
CANONICAL = re.compile(r"ja1_[0-9a-f]{32}:[0-9a-f]{12}:g1_[0-9a-f]{32}")


def key_of(lab, name: str, handle: str) -> str:
    """The canonical key that ``render_hint`` prints for one own allocation."""
    binding = lab.lab.table.get(lab.key(name).kd)
    (entry,) = [e for e in binding.jobs.values() if e.handle == handle]
    key = entry.job.canonical_key
    assert CANONICAL.fullmatch(key)  # nosec B101 - pytest assertion
    return key


def test_own_canonical_key_reads_the_same_page_as_the_handle(tmp_path):
    lab = make_lab(tmp_path / "phase")
    handle = lab.start("A", "R3-SYN-JOB-01")
    key = key_of(lab, "A", handle)
    outcome = lab.outcome("A")
    for page in (0, 1, 2):
        by_key = serving.read_page(lab.lab, outcome, key, page)
        assert isinstance(by_key, dict)  # nosec B101 - pytest assertion
        assert by_key == serving.read_page(lab.lab, outcome, handle, page)  # nosec B101 - pytest assertion
    assert serving.echo(lab.lab, outcome, key, VALUES_1) == {"ok": True}  # nosec B101 - pytest assertion


def test_canonical_key_with_a_repeated_slot_is_exact_not_ambiguous(tmp_path):
    lab = make_lab(tmp_path / "phase")
    first = lab.start("A", "R3-SYN-JOB-01")
    second = lab.start("A", "R3-SYN-JOB-01")
    outcome = lab.outcome("A")
    assert (  # nosec B101 - pytest assertion
        serving.read_page(lab.lab, outcome, "R3-SYN-JOB-01", 0)
        is LabError.AMBIGUOUS_SLOT
    )
    pages = [
        serving.read_page(lab.lab, outcome, key_of(lab, "A", h), 0)
        for h in (first, second)
    ]
    assert all(isinstance(p, dict) for p in pages)  # nosec B101 - pytest assertion
    assert pages[0]["alloc_tag"] != pages[1]["alloc_tag"]  # nosec B101 - pytest assertion


def test_foreign_guessed_malformed_and_retired_keys_are_uniform_denied(tmp_path):
    lab = make_lab(tmp_path / "phase")
    mine = lab.start("A", "R3-SYN-JOB-01")
    gone = lab.start("A", "R3-SYN-JOB-02")
    foreign = lab.start("B", "R3-SYN-JOB-03")
    own, retired = key_of(lab, "A", mine), key_of(lab, "A", gone)
    theirs = key_of(lab, "B", foreign)
    assert asyncio.run(serving.retire(lab.lab, lab.key("A"), gone))  # nosec B101 - pytest assertion
    ns, job_id, incarnation = own.split(":")
    other_ns, other_id, other_inc = theirs.split(":")
    selectors = [
        theirs,  # another chat's own key, copied verbatim
        f"{ns}:{other_id}:{other_inc}",  # own namespace, foreign job
        f"{other_ns}:{job_id}:{incarnation}",  # foreign namespace, own job
        f"{ns}:{job_id}:g1_" + "0" * 32,  # guessed incarnation
        f"{ns}:000000000000:{incarnation}",  # guessed job id
        "ja1_" + "0" * 32 + ":" + "0" * 12 + ":g1_" + "0" * 32,
        retired,
        own.upper(),
        own + "\n",
        " " + own,
        own[:-1],
        own + "0",
        own.replace(":", "/"),
        own.replace("ja1_", "ja2_"),
        own.replace(":g1_", ":g2_"),
        f"{ns}:{job_id}",
        "j_" + job_id + ":" + incarnation,
    ]
    outcome = lab.outcome("A")
    for selector in selectors:
        assert serving.read_page(lab.lab, outcome, selector, 0) is LabError.DENIED  # nosec B101 - pytest assertion
        assert serving.echo(lab.lab, outcome, selector, VALUES_1) is LabError.DENIED  # nosec B101 - pytest assertion
    # B's own key still works for B: the denial above is ownership, not grammar.
    assert isinstance(serving.read_page(lab.lab, lab.outcome("B"), theirs, 0), dict)  # nosec B101 - pytest assertion
    for broken in (
        RouteOutcome(RouteStatus.NO_SESSION),
        RouteOutcome(RouteStatus.MISMATCH),
        RouteOutcome(RouteStatus.MALFORMED, format_change=True),
    ):
        assert serving.read_page(lab.lab, broken, own, 0) is LabError.DENIED  # nosec B101 - pytest assertion


def test_canonical_key_gate_reads_nothing_global(tmp_path, monkeypatch):
    lab = make_lab(tmp_path / "phase")
    mine = lab.start("A", "R3-SYN-JOB-01")
    foreign = lab.start("B", "R3-SYN-JOB-02")
    own, theirs = key_of(lab, "A", mine), key_of(lab, "B", foreign)
    reads = {"ledger": 0, "catalog": 0, "check": 0, "lease": 0}
    for name, owner, attr in (
        ("ledger", lab.lab.ledger, "read"),
        ("catalog", lab.lab.snapshots.catalog, "lookup"),
        ("check", lab.lab.authority, "check"),
        ("lease", lab.lab.snapshots, "open_verified"),
    ):
        original = getattr(owner, attr)

        def counted(*args, _name=name, _original=original, **kwargs):
            reads[_name] += 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(owner, attr, counted)
    outcome = lab.outcome("A")
    guessed = own.rsplit(":", 1)[0] + ":g1_" + "f" * 32
    for selector in (theirs, guessed, own + "x"):
        assert serving.read_page(lab.lab, outcome, selector, 0) is LabError.DENIED  # nosec B101 - pytest assertion
    assert reads == {"ledger": 0, "catalog": 0, "check": 0, "lease": 0}  # nosec B101 - pytest assertion
    assert isinstance(serving.read_page(lab.lab, outcome, own, 0), dict)  # nosec B101 - pytest assertion
    assert reads["ledger"] == 1 and reads["lease"] == 1  # nosec B101 - pytest assertion
