"""Concurrent stop agreement for the durable job engine (split from lifecycle)."""

import sys
import threading

import pytest

from tests.integration.job_test_support import run, stop

LINUX_ONLY = pytest.mark.skipif(
    sys.platform != "linux",
    reason="no Darwin counterpart: durable jobs / Linux job engine are UNAVAILABLE on Darwin by release scope (CR0-04)",
)

pytestmark = LINUX_ONLY


def test_concurrent_stops_agree():
    p = run("sleep 30", background=True)
    results: list[dict] = []

    def go() -> None:
        results.append(stop(p["job_id"]))

    ts = [threading.Thread(target=go) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert [r["state"] for r in results] == ["exited", "exited"]
    assert {r["signal"] for r in results} == {15}
