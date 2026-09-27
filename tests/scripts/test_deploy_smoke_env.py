"""scripts/deploy_smoke.py's real boundaries: the command runner, the journal
reader, the MCP client and the default environment."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

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


def test_read_journal_bounds_the_window(monkeypatch: Any) -> None:
    seen: list[list[str]] = []

    def fake(argv: list[str], timeout: float) -> tuple[int, str]:
        seen.append(list(argv))
        return 0, "a\nb\n"

    monkeypatch.setattr(deploy_smoke, "run_command", fake)
    assert deploy_smoke.read_journal(100.7, 200.2) == ["a", "b"]
    assert "--since" in seen[0] and "@100" in seen[0] and "@201" in seen[0]
    assert deploy_smoke.read_journal(100.0) == ["a", "b"] and "--until" not in seen[1]


def test_read_journal_is_empty_when_journalctl_fails(monkeypatch: Any) -> None:
    monkeypatch.setattr(deploy_smoke, "run_command", lambda argv, timeout: (1, "boom"))
    assert deploy_smoke.read_journal(1.0) == []


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
