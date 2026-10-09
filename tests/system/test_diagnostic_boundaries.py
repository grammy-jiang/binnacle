"""Neutral diagnostics stay usable without another application's aggregate."""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "binnacle"


@pytest.mark.parametrize("module", ["watchdog_doctor", "watchdog_cli", "tunnel_cli"])
def test_companions_do_not_import_core_doctor_aggregate(module):
    folder = (
        "companions/watchdog" if module.startswith("watchdog") else "companions/tunnel"
    )
    tree = ast.parse((SRC / folder / f"{module}.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module != "binnacle.doctor"
            if node.module == "binnacle":
                assert all(alias.name != "doctor" for alias in node.names)


def test_neutral_rendering_keeps_public_exit_and_json_contract():
    from binnacle.diagnostics import doctor, doctor_render
    from binnacle.doctor_contracts import fail, ok, warn

    checks = [
        ok("local", "ready"),
        warn("remote", "slow", "retry"),
        fail("unit", "down"),
    ]
    assert doctor.render is doctor_render.render
    assert doctor.render_json is doctor_render.render_json
    text, code = doctor_render.render(iter(checks))
    assert code == 1
    assert text == (
        "binnacle doctor\n  [ok  ] local: ready\n  [WARN] remote: slow\n"
        "         hint: retry\n  [FAIL] unit: down\n1 ok, 1 warn, 1 fail"
    )
    assert doctor_render.render_json(checks) == doctor.render_json(checks)


@pytest.mark.parametrize("flag", ["--probe", "--no-probe"])
def test_core_probe_flags_remain_accepted_without_uplink(flag, monkeypatch, capsys):
    from binnacle import cli
    from binnacle.diagnostics import doctor

    calls = []
    monkeypatch.setattr(
        doctor, "run_all", lambda *a, **kw: calls.append(kw["probe"]) or []
    )
    with pytest.raises(SystemExit) as exc:
        cli.app(["doctor", flag])
    assert exc.value.code == 0
    assert calls == [flag == "--probe"]
    assert "0 ok, 0 warn, 0 fail" in capsys.readouterr().out
    assert not hasattr(doctor, "check_uplink")


@pytest.mark.parametrize("module", ["watchdog_cli", "tunnel_cli"])
def test_companions_do_not_import_core_cli(module):
    folder = (
        "companions/watchdog" if module.startswith("watchdog") else "companions/tunnel"
    )
    tree = ast.parse((SRC / folder / f"{module}.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module != "binnacle.cli"


def test_watchdog_uses_public_tunnel_log_facts():
    source = SRC / "companions/watchdog/ops/services.py"
    tree = ast.parse(source.read_text())
    assert not any(
        isinstance(n, ast.ImportFrom) and n.module == "binnacle.tunnel_doctor"
        for n in ast.walk(tree)
    )
