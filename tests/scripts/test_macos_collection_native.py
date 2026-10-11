"""Native collection receipts: default pytest discovery on the running OS.

These tests run real subprocesses (``pytest --collect-only``, ``sw_vers``) with
no mocks. They execute on Linux and macOS; only the Darwin-host probe is
OS-specific and it is skipped solely where ``sys.platform`` is not ``darwin``.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
OWNED = (
    "tests/platform/darwin/test_collection_contract.py",
    "tests/scripts/test_macos_collection_native.py",
    "tests/scripts/test_macos_test_selection.py",
)


def _collect(*targets: str) -> tuple[int, list[str], str]:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            *targets,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=55,
        check=False,
    )
    ids = [line for line in proc.stdout.splitlines() if "::" in line]
    return proc.returncode, ids, proc.stdout + proc.stderr


def test_owned_modules_collect_nonzero_node_ids_by_default_discovery():
    code, ids, out = _collect(*OWNED)
    assert code == 0, out
    for rel in OWNED:
        mine = [i for i in ids if i.startswith(rel + "::")]
        assert mine, f"{rel} collected zero tests"


def test_directory_collection_reaches_darwin_package_without_hooks():
    code, ids, out = _collect("tests/platform")
    assert code == 0, out
    assert any(
        i.startswith("tests/platform/darwin/test_collection_contract.py::") for i in ids
    )
    assert re.search(r"\d+ tests? collected", out)


def test_zero_collection_of_missing_darwin_module_is_an_error():
    code, ids, _ = _collect("tests/platform/darwin/test_does_not_exist.py")
    assert code != 0
    assert ids == []


@pytest.mark.skipif(
    sys.platform != "darwin", reason="Darwin host probe; Linux has no sw_vers"
)
def test_running_on_real_darwin_host():
    proc = subprocess.run(
        ["sw_vers", "-productName"],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert proc.stdout.strip()
    import platform

    assert platform.system() == "Darwin"
