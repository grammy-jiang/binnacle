"""Darwin test discovery contract (CR0-07 / R0-C9).

Native Darwin tests are found by ordinary ``test_*.py`` discovery under the
configured ``testpaths``; no collection hook or ``python_files`` override may be
introduced. These checks run on every OS: the frozen declarations import on
Linux and macOS, and nothing here skips a whole platform.
"""

import ast
import importlib
import importlib.util
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


def _selection_module():
    """The T0 skip scanner, loaded by path (tests/scripts is not a package)."""
    path = ROOT / "tests/scripts/test_macos_test_selection.py"
    spec = importlib.util.spec_from_file_location("_t0_skip_scanner", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _module_skips_everything(tree: ast.Module) -> bool:
    """True when any module-scope skip (mark, alias, call, autouse) hides tests."""
    return bool(_selection_module().whole_module_skips(ast.unparse(tree)))


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


@pytest.mark.parametrize(
    "source",
    [
        (
            "import pytest, sys\n"
            "pytestmark = pytest.mark.skipif(sys.platform != 'darwin', reason='x')\n"
        ),
        "import pytest\npytestmark = [pytest.mark.skip(reason='x')]\n",
        (
            "import pytest, sys\n"
            "NATIVE = pytest.mark.skipif(sys.platform != 'darwin', reason='x')\n"
            "pytestmark = NATIVE\n"
        ),
        (
            "import pytest, sys\n"
            "if sys.platform != 'darwin':\n"
            "    pytest.skip('x', allow_module_level=True)\n"
        ),
        "import pytest\npytest.skip('x', allow_module_level=True)\n",
    ],
)
def test_whole_platform_skip_detector_rejects_blanket_skips(source):
    assert _module_skips_everything(ast.parse(source))


def test_whole_platform_skip_detector_allows_narrow_skips():
    narrow = ast.parse(
        "import pytest, sys\npytestmark = pytest.mark.no_xdist\n"
        "NATIVE = pytest.mark.skipif(sys.platform != 'darwin', reason='x')\n"
        "@NATIVE\ndef test_a(): ...\n"
        "@pytest.mark.skipif(True, reason='x')\ndef test_b(): ...\n"
        "def test_c():\n"
        "    if sys.platform != 'darwin':\n        pytest.skip('x')\n"
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


NARROW = (
    "import pytest, sys\n"
    "@pytest.mark.skipif(sys.platform != 'darwin', reason='x')\n"
    "def test_a(): ...\n"
    "def test_b(): ...\n"
)
SEL = _selection_module()


# -- collection-time drops in conftest.py (R2D-T0-01) -----------------------

CONFTEST_DROPS = {
    "collect-ignore-glob-on-darwin": (
        "import sys\n"
        "if sys.platform == 'darwin':\n"
        "    collect_ignore_glob = ['test_*.py']\n"
    ),
    "collect-ignore-list": "collect_ignore = ['test_linux_only.py']\n",
    "collect-ignore-augmented": "collect_ignore = []\ncollect_ignore += ['x.py']\n",
    "collect-ignore-append": (
        "import sys\n"
        "collect_ignore = []\n"
        "if sys.platform == 'darwin':\n"
        "    collect_ignore.append('test_linux_only.py')\n"
    ),
    "collect-ignore-in-else-branch": (
        "import sys\n"
        "if sys.platform == 'linux':\n"
        "    pass\n"
        "else:\n"
        "    collect_ignore_glob = ['*.py']\n"
    ),
    "hook-assignment": (
        "import sys\n"
        "pytest_ignore_collect = lambda collection_path: sys.platform == 'darwin'\n"
    ),
    "hook-imported": "from helpers import pytest_ignore_collect\n",
    "hook-function": (
        "import sys\n"
        "def pytest_ignore_collect(collection_path):\n"
        "    return sys.platform == 'darwin'\n"
    ),
}


@pytest.mark.parametrize("name", sorted(CONFTEST_DROPS))
def test_scanner_reports_conftest_collection_drops_as_whole_module(name):
    sites = SEL.scan_skips(CONFTEST_DROPS[name], conftest=True)
    assert sites and all(s.scope == "module" for s in sites), sites
    # Without the conftest flag a normal test module is not affected.
    assert not SEL.scan_skips(CONFTEST_DROPS[name])


@pytest.mark.parametrize("name", sorted(CONFTEST_DROPS))
def test_policy_rejects_conftest_collection_drops_in_the_darwin_package(name):
    rel = "tests/platform/darwin/conftest.py"
    problems = SEL.check_skip_policy(
        {rel: CONFTEST_DROPS[name]}, {rel: "A2: listed anyway"}
    )
    assert any("whole-module skip is forbidden" in p for p in problems), problems


def test_policy_rejects_unconditional_collect_ignore_anywhere_and_platform_ones():
    plain = "collect_ignore = ['x.py']\n"
    assert SEL.check_skip_policy({"tests/unit/conftest.py": plain}, {})
    gated = CONFTEST_DROPS["collect-ignore-glob-on-darwin"]
    assert SEL.check_skip_policy({"tests/unit/conftest.py": gated}, {})
    benign = "def pytest_configure(config): ...\nx = 1\n"
    assert not SEL.check_skip_policy({"tests/unit/conftest.py": benign}, {})


# -- per-row platform-site counts (R2D-T0-02) ---------------------------------

TWO_SKIPS = NARROW + (
    "@pytest.mark.skipif(sys.platform == 'darwin', reason='extra')\ndef test_x(): ...\n"
)


def test_policy_pins_the_platform_site_count_per_row():
    rel = "tests/platform/darwin/test_search_parity.py"
    table = {rel: "A4: narrow"}
    assert SEL.check_skip_policy({rel: NARROW}, table, counts={rel: 1}) == []
    problems = SEL.check_skip_policy({rel: TWO_SKIPS}, table, counts={rel: 1})
    assert len(problems) == 1 and "row pins 1" in problems[0], problems
    problems = SEL.check_skip_policy({rel: NARROW}, table, counts={rel: 2})
    assert len(problems) == 1 and "row pins 2" in problems[0], problems
    problems = SEL.check_skip_policy({rel: NARROW}, table, counts={})
    assert len(problems) == 1 and "row pins None" in problems[0], problems


def test_policy_pin_counts_non_darwin_baseline_rows_too():
    rel = "tests/system/test_uplink_network.py"
    table = {rel: "baseline: Linux only"}
    assert SEL.check_skip_policy({rel: NARROW}, table, counts={rel: 1}) == []
    assert SEL.check_skip_policy({rel: TWO_SKIPS}, table, counts={rel: 1})


def test_policy_pin_counts_suspect_flags_as_platform_sites():
    rel = "tests/platform/darwin/test_a.py"
    source = (
        NARROW
        + "from os.path import supports_unicode_filenames as ON_MAC\n@pytest.mark.skipif(ON_MAC)\ndef test_y(): ...\n"
    )
    problems = SEL.check_skip_policy({rel: source}, {rel: "A2: y"}, counts={rel: 1})
    assert len(problems) == 1 and "2 platform skip sites" in problems[0], problems


# -- module-level importorskip allow-list (R2D-T0-01) -------------------------


def test_policy_allows_only_the_named_module_level_importorskip():
    source = "import pytest\ntomllib = pytest.importorskip('tomllib')\n"
    rel = "tests/contracts/test_dependency_pin.py"
    assert ("tests/contracts/test_dependency_pin.py", "tomllib") in (
        SEL.ALLOWED_MODULE_IMPORTORSKIPS
    )
    assert SEL.check_skip_policy({rel: source}, {}) == []
    other = source.replace("tomllib", "fcntl")
    assert SEL.check_skip_policy({rel: other}, {})
    assert SEL.check_skip_policy({"tests/unit/test_new.py": source}, {})
    darwin = "tests/platform/darwin/test_dependency_pin.py"
    assert SEL.check_skip_policy({darwin: source}, {})
    local = "import pytest\ndef test_a():\n    pytest.importorskip('fcntl')\n"
    assert SEL.check_skip_policy({"tests/unit/test_new.py": local}, {}) == []


def test_uplink_linux_only_skip_marks_individual_cases_not_the_module():
    path = ROOT / "tests/system/test_uplink_network.py"
    tree = ast.parse(path.read_text())
    module_marks = [
        n
        for n in tree.body
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in n.targets)
    ]
    assert module_marks == []
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    narrow = [
        f
        for f in functions
        if any(
            isinstance(d, ast.Name) and d.id == "linux_integration"
            for d in f.decorator_list
        )
    ]
    assert 0 < len(narrow) < len(functions)
