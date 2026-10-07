"""Regressions for the former G5 reverse edges and narrow companion imports."""

import pytest

from scripts import check_architecture as architecture

POLICY = architecture.load_policy()


@pytest.mark.parametrize(
    ("source", "forbidden"),
    [
        ("binnacle.watchdog_doctor", "binnacle.doctor"),
        ("binnacle.watchdog_cli", "binnacle.doctor"),
        ("binnacle.tunnel_cli", "binnacle.doctor"),
        ("binnacle.tunnel_doctor", "binnacle.doctor_connectivity"),
        ("binnacle.watchdog_cli", "binnacle.cli"),
        ("binnacle.tunnel_cli", "binnacle.cli"),
        ("binnacle.ops.watchdog.services", "binnacle.tunnel_doctor"),
        ("binnacle.doctor_connectivity", "binnacle.uplink"),
        ("binnacle.cli", "binnacle.webminstats"),
    ],
)
def test_former_reverse_edges_fail_for_import_spellings(tmp_path, source, forbidden):
    path = tmp_path / "source.py"
    module = forbidden.rsplit(".", 1)[1]
    statements = [
        f"import {forbidden}",
        f"from binnacle import {module}",
        f"from {forbidden} import member",
    ]
    if source.count(".") == 1:
        statements.append(f"from . import {module}")
    for statement in statements:
        path.write_text(statement)
        imports = architecture.imports_of(path, source)
        assert architecture.evaluate({source: imports}, POLICY), statement


@pytest.mark.parametrize(
    ("statement", "valid"),
    [
        ("from binnacle.tunnel_unit import TUNNEL_UNIT", True),
        ("from .tunnel_unit import TUNNEL_UNIT", True),
        ("from binnacle import tunnel_unit", False),
        ("import binnacle.tunnel_unit", False),
        ("from binnacle.tunnel_unit import TUNNEL_UNIT, render_tunnel_unit", False),
        ("from binnacle.tunnel_unit import *", False),
        ("", False),
        (
            "import binnacle.tunnel_unit\nfrom binnacle.tunnel_unit import TUNNEL_UNIT",
            False,
        ),
    ],
)
def test_watchdog_identity_is_only_the_declared_symbol(tmp_path, statement, valid):
    path = tmp_path / "watchdog_cli.py"
    path.write_text(statement)
    assert (
        bool(architecture.public_import_errors(path, "binnacle.watchdog_cli", POLICY))
        != valid
    )


def test_only_services_can_use_public_tunnel_log(tmp_path):
    path = tmp_path / "services.py"
    path.write_text("from binnacle.tunnel_log import scan_tunnel_log")
    source = "binnacle.ops.watchdog.services"
    assert architecture.public_import_errors(path, source, POLICY) == []
    assert (
        architecture.evaluate({source: architecture.imports_of(path, source)}, POLICY)
        == []
    )
    assert architecture.evaluate(
        {"binnacle.watchdog_doctor": {"binnacle.tunnel_log.scan_tunnel_log"}}, POLICY
    )
    path.write_text("from binnacle.tunnel_log import _tail_lines")
    assert architecture.public_import_errors(path, source, POLICY)
