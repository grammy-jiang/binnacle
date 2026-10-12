"""J7m-W3 is a strictly additive start-up import health check."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from scripts import mac_w3_deploy_gate as w3

OK = {"checks": [{"group": "startup", "status": "ok", "detail": "clear"}]}
BAD = {
    "checks": [
        {
            "group": "startup",
            "status": "fail",
            "detail": "module=binnacle.broken error_class=SyntaxError at=binnacle/broken.py:2",
        }
    ]
}


def _base_gate(doctor: dict | str, *, smoke: bool = True):
    class Gate:
        def __init__(self):
            self.a = SimpleNamespace(checkout=Path("/owned/frozen-candidate"))
            self.seen = []

        def run(self, argv, timeout, cwd):
            self.seen.append((argv, timeout, cwd))
            return (0, json.dumps(doctor)) if isinstance(doctor, dict) else (70, doctor)

        def step(self, name, decision, **data):
            self.seen.append((name, decision, data))
            return decision

        def step_smoke(self, name, sha, via_manager=False):
            return smoke

    base = SimpleNamespace(
        Gate=Gate,
        FAIL_REASONS=(("existing_failure", "already owns"),),
        FAIL_EXIT_REASONS={75: "busy"},
    )
    w3.add_w3_checks(base)
    return base.Gate()


def test_doctor_parser_fails_closed_on_missing_corrupt_or_failed_start():
    assert w3.parse_startup_doctor(json.dumps(OK)) == (True, "startup_ok", [])
    assert w3.parse_startup_doctor(json.dumps(OK) + "\nWARNING configuration detected")[
        0
    ]
    assert not w3.parse_startup_doctor(json.dumps({"checks": []}))[0]
    assert not w3.parse_startup_doctor(json.dumps({"checks": "wrong"}))[0]
    assert not w3.parse_startup_doctor("invalid")[0]
    yes, why, details = w3.parse_startup_doctor(json.dumps(BAD))
    assert not yes and why == "startup_failure"
    assert "binnacle/broken.py:2" in details[0]


def test_w3_gate_invokes_doctor_only_after_real_smoke():
    good = _base_gate(OK)
    assert good.step_smoke("7_live_smoke", "a" * 40, via_manager=True)
    assert good.seen[0][0][1:] == ["doctor", "--json"]
    assert good.seen[-1][0] == "7a_startup_doctor"
    assert good.seen[-1][1]

    broken = _base_gate(BAD)
    assert not broken.step_smoke("7_live_smoke", "a" * 40)
    assert broken.seen[-1][2]["reason"] == "startup_failure"

    failed_smoke = _base_gate(OK, smoke=False)
    assert not failed_smoke.step_smoke("7_live_smoke", "a" * 40)
    assert not failed_smoke.seen
    rollback = _base_gate(BAD)
    assert rollback.step_smoke("8d_rollback_smoke", "a" * 40)
    assert not rollback.seen


def test_w3_preserves_original_reasons_and_includes_new_ones():
    base = SimpleNamespace(
        Gate=type("Gate", (), {"step_smoke": lambda *_a, **_k: True}),
        FAIL_REASONS=(("old", "old_marker"),),
        FAIL_EXIT_REASONS={75: "busy"},
    )
    w3.add_w3_checks(base)
    assert base.FAIL_REASONS[0] == (
        "startup_import_failed",
        "event=startup_import_failed",
    )
    assert base.FAIL_REASONS[-1] == ("old", "old_marker")
    assert base.FAIL_EXIT_REASONS == {75: "busy", 70: "EX_STARTUP_IMPORT"}


def test_base_verification_rejects_any_unreviewed_gate(tmp_path):
    untrusted = tmp_path / "gate.py"
    untrusted.write_text("print('this must never be executed')\n")
    try:
        w3.verified_gate(untrusted)
    except ValueError as exc:
        assert "hash mismatch" in str(exc)
    else:
        raise AssertionError("modified gate executed without an exact SHA pin")
