"""scripts/deploy_smoke.py's real boundaries: the command runner, the journal
reader, the MCP client and the default environment."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from binnacle.platform.contracts.service_log_contracts import ServiceLogError
from scripts import deploy_smoke


def test_run_command_returns_code_and_output() -> None:
    rc, out = deploy_smoke.run_command([sys.executable, "-c", "print('hi')"], 30)
    assert rc == 0 and out.strip() == "hi"


def test_run_command_reports_a_missing_program() -> None:
    rc, out = deploy_smoke.run_command(["/nonexistent/binnacle-smoke-tool"], 5)
    assert rc == 127 and out


def test_run_command_reports_a_timeout() -> None:
    rc, out = deploy_smoke.run_command(
        [sys.executable, "-c", "import time; time.sleep(5)"], 0.2
    )
    assert rc == 124 and "timed out" in out


def test_read_journal_uses_semantic_source_and_60_second_bound(
    monkeypatch: Any,
) -> None:
    seen: dict[str, object] = {}

    class Source:
        def read_window(self, services, since_epoch, until_epoch=None):
            seen["services"] = tuple(services)
            seen["since"] = since_epoch
            seen["until"] = until_epoch
            return "a\nb\n"

    def factory(*, command_timeout_s):
        seen["timeout"] = command_timeout_s
        return Source()

    monkeypatch.setattr(deploy_smoke, "create_service_log_source", factory)

    assert deploy_smoke.read_journal(100.7, 200.2) == ["a", "b"]
    assert seen == {
        "timeout": 60.0,
        "services": (deploy_smoke.UNIT,),
        "since": 100.7,
        "until": 200.2,
    }


def test_read_journal_propagates_typed_acquisition_failure(monkeypatch: Any) -> None:
    class BrokenSource:
        def read_window(self, services, since_epoch, until_epoch=None):
            raise ServiceLogError("boom")

    monkeypatch.setattr(
        deploy_smoke,
        "create_service_log_source",
        lambda *, command_timeout_s: BrokenSource(),
    )

    with pytest.raises(ServiceLogError, match="boom"):
        deploy_smoke.read_journal(1.0)


def test_mcp_client_reads_the_bearer_token_file(
    tmp_path: Path, monkeypatch: Any
) -> None:
    token = tmp_path / "token"
    token.write_text("Bearer secret-value\n", encoding="utf-8")
    monkeypatch.setattr(deploy_smoke, "TOKEN_FILE", token)
    client = deploy_smoke.mcp_client()
    assert client is not None


def test_default_env_points_at_the_production_checkout(tmp_path: Path) -> None:
    env = deploy_smoke.default_env(tmp_path)
    assert env.checkout == tmp_path and env.tmp_root == Path("/tmp")
    assert env.read(Path(__file__)).startswith('"""')
    assert env.now() > 0
