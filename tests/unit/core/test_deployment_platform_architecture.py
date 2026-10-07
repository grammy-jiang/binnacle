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
    ROOT / "scripts/deploy_smoke.py",
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


def _is_forbidden_path_text(text: str) -> bool:
    return text in {"/proc", "/sys/fs/cgroup"} or text.startswith(
        ("/proc/", "/sys/fs/cgroup/", "/run/user/")
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
                if fn in {"Path", "pathlib.Path"} and _is_forbidden_path_text(text):
                    violations.append(
                        f"{path.name}:{node.lineno}: executable Linux path {text}"
                    )

            for arg in (*node.args, *(kw.value for kw in node.keywords)):
                if isinstance(arg, (ast.List, ast.Tuple)):
                    argv_texts = _literal_text(arg)
                    command_like = bool(argv_texts) and (
                        argv_texts[0] in FORBIDDEN_COMMANDS or argv_texts[0] == "date"
                    )
                    if command_like and argv_texts[0] in FORBIDDEN_COMMANDS:
                        violations.append(
                            f"{path.name}:{node.lineno}: direct platform argv {argv_texts}"
                        )
                    if command_like and "date" in argv_texts and "-d" in argv_texts:
                        violations.append(
                            f"{path.name}:{node.lineno}: direct date -d conversion"
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
            value = node.value
            if isinstance(value, (ast.List, ast.Tuple)):
                texts = _literal_text(value)
                command_like = bool(texts) and (
                    texts[0] in FORBIDDEN_COMMANDS or texts[0] == "date"
                )
                if command_like and texts[0] in FORBIDDEN_COMMANDS:
                    violations.append(
                        f"{path.name}:{node.lineno}: platform argv construction {texts}"
                    )
                if command_like:
                    for text in texts:
                        if text in FORBIDDEN_EXACT:
                            violations.append(
                                f"{path.name}:{node.lineno}: executable platform token {text}"
                            )
                        if _is_forbidden_path_text(text):
                            violations.append(
                                f"{path.name}:{node.lineno}: executable Linux path {text}"
                            )
                if command_like and "date" in texts and "-d" in texts:
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
        elif isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(
            node.value, (ast.List, ast.Tuple)
        ):
            executable.extend(_literal_text(node.value))
    assert all(token not in text for text in executable for token in banned)
    assert _executable_platform_violations(path) == []


@pytest.mark.parametrize(
    "property_name",
    ["ControlGroup", "ExecMainStartTimestamp"],
)
def test_platform_detector_catches_indirect_prebuilt_systemctl_commands(
    tmp_path: Path, property_name: str
) -> None:
    path = tmp_path / "smoke_checks.py"
    path.write_text(
        "def probe(env):\n"
        f"    show = ['systemctl', '--user', 'show', 'svc', '-p', "
        f"'{property_name}', '--value']\n"
        "    return env.run(show)\n",
        encoding="utf-8",
    )

    violations = _executable_platform_violations(path)

    assert any("platform argv construction" in item for item in violations)
    assert any(property_name in item for item in violations)


@pytest.mark.parametrize(
    ("source", "needle"),
    [
        (
            """def probe(env, UNIT, timeout):
    return env.run(['systemctl', '--user', 'restart', UNIT], timeout)
""",
            "direct platform argv",
        ),
        (
            """def probe(run_command, UNIT):
    return run_command(['journalctl', '--user', '-u', UNIT, '--since', '@1'], 60)
""",
            "direct platform argv",
        ),
        (
            """from pathlib import Path
def probe(pid):
    return Path('/proc') / str(pid) / 'status'
""",
            "executable Linux path /proc",
        ),
        (
            """from pathlib import Path
def probe(pid):
    return Path('/proc') / str(pid) / 'environ'
""",
            "executable Linux path /proc",
        ),
    ],
)
def test_platform_detector_catches_former_direct_linux_mechanisms(
    tmp_path: Path, source: str, needle: str
) -> None:
    path = tmp_path / "generic.py"
    path.write_text(source, encoding="utf-8")

    violations = _executable_platform_violations(path)

    assert any(needle in item for item in violations)
