"""G4 platform-mechanism ownership and smoke-boundary regressions."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
GENERIC_PATHS = (
    ROOT / "src/binnacle/cli.py",
    ROOT / "src/binnacle/config.py",
    ROOT / "src/binnacle/doctor.py",
    ROOT / "src/binnacle/doctor_common.py",
    ROOT / "src/binnacle/doctor_jobs.py",
    ROOT / "src/binnacle/job_manager_doctor.py",
    ROOT / "src/binnacle/logstats_io.py",
    ROOT / "scripts/deploy_flow.py",
    ROOT / "scripts/smoke_checks.py",
)
FORBIDDEN_COMMANDS = {"systemctl", "journalctl", "loginctl"}
FORBIDDEN_EXACT = {
    "XDG_RUNTIME_DIR",
    "ControlGroup",
    "ExecMainStartTimestamp",
}
FORBIDDEN_PATH_PARTS = (
    "/run/user/",
    "/sys/fs/cgroup",
    "/proc/",
)


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _literal_text(node: ast.AST) -> list[str]:
    values: list[str] = []
    for part in ast.walk(node):
        if isinstance(part, ast.Constant) and isinstance(part.value, str):
            values.append(part.value)
        elif isinstance(part, ast.JoinedStr):
            static = "".join(
                value.value
                for value in part.values
                if isinstance(value, ast.Constant) and isinstance(value.value, str)
            )
            if static:
                values.append(static)
    return values


def _executable_platform_violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = _dotted(node.func)
            texts = []
            for arg in (*node.args, *(kw.value for kw in node.keywords)):
                texts.extend(_literal_text(arg))

            for text in texts:
                if text in FORBIDDEN_EXACT:
                    violations.append(
                        f"{path.name}:{node.lineno}: executable platform token {text}"
                    )
                if fn in {"Path", "pathlib.Path"} and any(
                    part in text for part in FORBIDDEN_PATH_PARTS
                ):
                    violations.append(
                        f"{path.name}:{node.lineno}: executable Linux path {text}"
                    )

            if fn in {"units.systemctl", "_doctor_common.systemctl"}:
                violations.append(
                    f"{path.name}:{node.lineno}: direct platform helper {fn}"
                )

            if fn.startswith("subprocess."):
                if any(text in FORBIDDEN_COMMANDS for text in texts):
                    violations.append(
                        f"{path.name}:{node.lineno}: direct platform subprocess {texts}"
                    )
                if "date" in texts and "-d" in texts:
                    violations.append(
                        f"{path.name}:{node.lineno}: direct date -d conversion"
                    )

        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            target_names = {
                target.id for target in targets if isinstance(target, ast.Name)
            }
            value = node.value
            if target_names & {"argv", "args", "cmd", "command"} and isinstance(
                value, (ast.List, ast.Tuple)
            ):
                texts = _literal_text(value)
                if any(text in FORBIDDEN_COMMANDS for text in texts):
                    violations.append(
                        f"{path.name}:{node.lineno}: platform argv construction {texts}"
                    )
                if "date" in texts and "-d" in texts:
                    violations.append(
                        f"{path.name}:{node.lineno}: direct date -d construction"
                    )

    return violations


@pytest.mark.parametrize("path", GENERIC_PATHS, ids=lambda path: path.name)
def test_g4_generic_paths_do_not_own_linux_execution_mechanisms(path: Path) -> None:
    assert _executable_platform_violations(path) == []


def test_smoke_measurement_uses_only_semantic_service_inspection() -> None:
    path = ROOT / "scripts/smoke_checks.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    calls = {
        _dotted(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)
    }

    assert "env.services.rss_kb" in calls
    assert "env.services.started_at_epoch" in calls

    banned = {
        "ControlGroup",
        "ExecMainStartTimestamp",
        "/sys/fs/cgroup",
        "/proc/",
    }
    executable = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for arg in (*node.args, *(kw.value for kw in node.keywords)):
                executable.extend(_literal_text(arg))
    assert all(token not in text for text in executable for token in banned)
    assert _executable_platform_violations(path) == []
