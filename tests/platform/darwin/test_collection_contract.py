"""Darwin test discovery contract (CR0-07 / R0-C9).

Native Darwin tests are found by ordinary ``test_*.py`` discovery under the
configured ``testpaths``; no collection hook or ``python_files`` override may be
introduced. These checks run on every OS: the frozen declarations import on
Linux and macOS, and nothing here skips a whole platform.
"""

import ast
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
DARWIN_TESTS = ROOT / "tests/platform/darwin"
CONTRACTS = (
    "capability_contracts",
    "darwin_contracts",
    "file_access_contracts",
    "metric_log_contracts",
    "native_service_contracts",
    "process_contracts",
    "resource_contracts",
    "runtime_path_contracts",
    "service_lifecycle_contracts",
    "service_log_contracts",
    "stop_contracts",
)
SUPPORT_MODULES = {"__init__.py", "conftest.py"}


def _module_skips_everything(tree: ast.Module) -> bool:
    """True when a module-level ``pytestmark`` skips the whole file."""
    for node in tree.body:
        if not (
            isinstance(node, ast.Assign)
            and any(
                isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets
            )
        ):
            continue
        marks = node.value.elts if isinstance(node.value, ast.List) else [node.value]
        for mark in marks:
            call = mark.func if isinstance(mark, ast.Call) else mark
            if isinstance(call, ast.Attribute) and call.attr == "skip":
                return True
            if (
                isinstance(mark, ast.Call)
                and isinstance(call, ast.Attribute)
                and call.attr == "skipif"
            ):
                condition = ast.unparse(mark.args[0]) if mark.args else ""
                if "platform" in condition or "system" in condition:
                    return True
    return False


def test_darwin_test_modules_use_default_discovery_names():
    modules = sorted(p.name for p in DARWIN_TESTS.glob("*.py"))
    assert "test_collection_contract.py" in modules
    for name in modules:
        assert name in SUPPORT_MODULES or name.startswith("test_"), name


def test_pytest_discovery_is_not_customised():
    text = (ROOT / "pyproject.toml").read_text()
    section = text.split("[tool.pytest.ini_options]", 1)[1].split("\n[", 1)[0]
    assert 'testpaths = ["tests"]' in section
    for key in ("python_files", "python_classes", "python_functions"):
        assert key not in section
    for conftest in (ROOT / "tests").rglob("conftest.py"):
        names = {
            n.name
            for n in ast.walk(ast.parse(conftest.read_text()))
            if isinstance(n, ast.FunctionDef)
        }
        assert not names & {
            "pytest_collect_file",
            "pytest_collection_modifyitems",
            "pytest_ignore_collect",
        }, conftest


def test_no_darwin_test_module_skips_its_whole_platform():
    for path in DARWIN_TESTS.glob("test_*.py"):
        tree = ast.parse(path.read_text())
        assert not _module_skips_everything(tree), path.name


def test_whole_platform_skip_detector_rejects_blanket_skips():
    blanket = ast.parse(
        "import pytest, sys\n"
        "pytestmark = pytest.mark.skipif(sys.platform != 'darwin', reason='x')\n"
    )
    assert _module_skips_everything(blanket)
    assert _module_skips_everything(
        ast.parse("import pytest\npytestmark = [pytest.mark.skip(reason='x')]\n")
    )
    narrow = ast.parse(
        "import pytest\npytestmark = pytest.mark.no_xdist\n"
        "@pytest.mark.skipif(True, reason='x')\ndef test_a(): ...\n"
    )
    assert not _module_skips_everything(narrow)


@pytest.mark.parametrize("name", CONTRACTS)
def test_frozen_contract_declarations_import_on_every_platform(name):
    module = importlib.import_module(f"binnacle.platform.contracts.{name}")
    assert module.__name__.endswith(name)


def test_importing_darwin_namespace_does_not_enable_native_capabilities():
    capability = importlib.import_module(
        "binnacle.platform.contracts.capability_contracts"
    )
    importlib.import_module("binnacle.platform.darwin")
    unavailable = capability.Capability(
        capability.CapabilityState.UNAVAILABLE, "not_implemented", "test"
    )
    error = capability.CapabilityUnavailable("not_implemented", unavailable)
    assert error.code == "not_implemented"
    assert error.capability.state is capability.CapabilityState.UNAVAILABLE


def test_default_discovery_collects_this_module_with_exact_node_ids():
    target = "tests/platform/darwin/test_collection_contract.py"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            target,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=50,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    ids = [line for line in proc.stdout.splitlines() if "::" in line]
    assert f"{target}::test_darwin_test_modules_use_default_discovery_names" in ids
    assert f"{target}::test_no_darwin_test_module_skips_its_whole_platform" in ids
    assert len(ids) >= 6 + len(CONTRACTS)
    assert not any("skip" in line.lower() for line in proc.stdout.splitlines()[-2:])


def test_t0_owned_modules_exist_with_discoverable_names():
    for rel in (
        "tests/platform/darwin/test_collection_contract.py",
        "tests/scripts/test_macos_collection_native.py",
        "tests/scripts/test_macos_test_selection.py",
    ):
        assert (ROOT / rel).is_file(), rel
        assert (ROOT / rel).name.startswith("test_")
