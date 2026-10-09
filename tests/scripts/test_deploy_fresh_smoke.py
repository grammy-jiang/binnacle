"""The deployment controller must execute the target checkout's fresh smoke."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from scripts import deploy_flow as flow
from scripts.smoke_checks import Env
from tests.service_fakes import FakeServiceController, FakeServiceInspector


def fake_env(root: Path, run: Callable[[Sequence[str], float], tuple[int, str]]) -> Env:
    return Env(
        run=run,
        journal=lambda since, until: [],
        now=lambda: 0.0,
        sleep=lambda seconds: None,
        client=lambda: None,
        read=lambda path: "",
        services=FakeServiceInspector(),
        service_controller=FakeServiceController(),
        checkout=root,
        state_dir=root / "state",
        tmp_root=root,
    )


OK = "OK: live smoke passed (2 checks)\n  [ok   ] doctor: ok\n  [ok   ] journal: 12/12 calls logged\n"
WARN = "WARN: rss_kb: elevated\n  [ok   ] journal: 12/12 calls logged\n  [warn ] rss_kb: elevated\n"
ALERT = "ALERT: journal failed\n  [ok   ] doctor: ok\n  [alert] journal: 3/12 calls logged\n"


@pytest.mark.parametrize(
    ("status", "output", "expected"),
    [
        (0, OK, "ok"),
        (0, WARN, "warn"),
        (1, ALERT, "alert"),
        (0, ALERT, "alert"),
        (1, OK, "alert"),
        (124, "timed out", "alert"),
        (0, "unparsable success", "alert"),
        (0, "OK: empty\n", "alert"),
        (0, OK + OK, "alert"),
        (0, "OK: misleading\n  [alert] journal: failed\n", "alert"),
    ],
)
def test_fresh_smoke_fail_closed_on_inconsistent_process_evidence(
    tmp_path: Path, status: int, output: str, expected: str
) -> None:
    observed: list[tuple[list[str], float]] = []

    def runner(argv: Sequence[str], timeout: float) -> tuple[int, str]:
        observed.append((list(argv), timeout))
        return status, output

    env = fake_env(tmp_path, runner)
    result = flow._fresh_smoke(env)
    assert result.level == expected
    if status == 0 and output in (OK, WARN):
        assert [entry.name for entry in result.checks] == (
            ["doctor", "journal"] if output == OK else ["journal", "rss_kb"]
        )
        assert not any(entry.name == "fresh_smoke" for entry in result.checks)
    else:
        assert result.level == "alert"
    assert observed == [
        (
            [
                str(tmp_path / ".venv/bin/python"),
                str(tmp_path / "scripts/deploy_smoke.py"),
                "--checkout",
                str(tmp_path),
            ],
            flow._FRESH_SMOKE_TIMEOUT_S,
        )
    ]


def test_fresh_smoke_reexecutes_changed_target_script_not_cached_import(
    tmp_path: Path,
) -> None:
    binary = tmp_path / ".venv/bin/python"
    binary.parent.mkdir(parents=True)
    binary.symlink_to(sys.executable)
    script = tmp_path / "scripts/deploy_smoke.py"
    script.parent.mkdir(parents=True)

    def runner(argv: Sequence[str], timeout: float) -> tuple[int, str]:
        proc = subprocess.run(
            argv, capture_output=True, text=True, check=False, timeout=timeout
        )
        return proc.returncode, proc.stdout + proc.stderr

    env = fake_env(tmp_path, runner)
    script.write_text(
        'print("OK: from current tree")\n'
        'print("  [ok   ] journal: matched current schema")\n'
    )
    assert flow._fresh_smoke(env).level == "ok"
    script.write_text(
        'print("ALERT: new code rejects incorrect log")\n'
        'print("  [alert] journal: failed new schema")\n'
        "raise SystemExit(1)\n"
    )
    final = flow._fresh_smoke(env)
    assert final.level == "alert"
    assert any(
        entry.name == "journal" and "new schema" in entry.detail
        for entry in final.checks
    )
