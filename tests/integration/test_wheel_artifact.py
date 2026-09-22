"""Build the distributable wheel and inspect its release-critical contents."""

import shutil
import subprocess
import zipfile
from pathlib import Path


def test_wheel_contains_runtime_package_typing_marker_and_entry_points(tmp_path):
    repo = Path(__file__).resolve().parents[2]
    project = tmp_path / "project"
    project.mkdir()
    shutil.copy2(repo / "pyproject.toml", project / "pyproject.toml")
    shutil.copytree(
        repo / "src",
        project / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"),
    )
    dist = project / "dist"

    uv = shutil.which("uv")
    assert uv is not None, "uv is required by the repository's build workflow"
    proc = subprocess.run(
        [uv, "build", "--wheel", "--out-dir", str(dist)],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr

    wheels = list(dist.glob("*.whl"))
    assert len(wheels) == 1

    with zipfile.ZipFile(wheels[0]) as archive:
        names = set(archive.namelist())
        assert "binnacle/server.py" in names
        assert "binnacle/cli.py" in names
        assert "binnacle/py.typed" in names
        assert "binnacle/tools/read_file.py" in names
        assert "binnacle/tools/run_command.py" in names
        assert "binnacle/ops/watchdog/policy.py" in names
        assert not any(name.startswith("tests/") for name in names)

        entry_points = next(
            name for name in names if name.endswith(".dist-info/entry_points.txt")
        )
        entries = archive.read(entry_points).decode()
        assert "binnacle = binnacle.cli:main" in entries
        assert "binnacle-jobs = binnacle.job_manager:main" in entries
        assert "binnacle-watchdog = binnacle.watchdog_cli:main" in entries
