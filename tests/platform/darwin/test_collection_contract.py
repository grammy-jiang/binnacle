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


# -- Linux-only pins: the LINUX_ONLY alias is pinned per file ---------------
# (uses = decorated tests/params, nodes = collected pytest nodes). Reusing the
# alias on another test fails check_skip_policy until this table is edited.
_PIN_TABLE = """
descriptions 1 1
golden_outputs 1 1
job_schemas 4 4
job_spool_compat 4 4
job_status_cursor_internal 12 12
os_stage1_wire_parity 2 2
search_text_surface 2 2
server_composition 2 6
tool_surface 2 4
"""
_PIN_ROWS = [r.split() for r in _PIN_TABLE.strip().splitlines()]
LINUX_PIN_USE_COUNTS = {f"tests/contracts/test_{n}.py": int(u) for n, u, _ in _PIN_ROWS}
LINUX_PIN_NODE_COUNTS = {
    f"tests/contracts/test_{n}.py": int(c) for n, _, c in _PIN_ROWS
}
for _file, _uses in (
    ("composition_workflows", 3),
    ("os_pure_application", 1),
):
    _rel = f"tests/integration/test_{_file}.py"
    LINUX_PIN_USE_COUNTS[_rel] = LINUX_PIN_NODE_COUNTS[_rel] = _uses
_T0A9_PIN_TABLE = """
tests/integration/test_cli.py 3 3
tests/integration/test_commands_settings.py 3 3
tests/integration/test_http_workflows.py 2 2
tests/integration/test_job_manager.py 1 22
tests/integration/test_job_manager_reload.py 1 1
tests/integration/test_job_manager_telemetry.py 2 2
tests/integration/test_job_telemetry.py 1 1
tests/integration/test_jobs.py 1 25
tests/integration/test_jobs_lifecycle.py 1 36
tests/integration/test_jobs_lifecycle_stops.py 1 1
tests/integration/test_jobs_state_machine.py 1 1
tests/integration/test_jobs_stop_paths.py 1 1
tests/integration/test_jobs_store.py 6 6
tests/integration/test_log_privacy.py 2 2
tests/integration/test_logging.py 1 1
tests/integration/test_logging_jobs.py 1 4
tests/integration/test_mounted_call_context.py 1 1
tests/integration/test_os_job_rpc_cross_version.py 1 2
tests/integration/test_packaging_smoke.py 1 1
tests/integration/test_root_settings.py 1 1
tests/scripts/test_deploy_smoke_env.py 1 1
tests/system/test_diagnostic_boundaries.py 1 2
tests/system/test_doctor.py 3 3
tests/system/test_doctor_coverage.py 2 3
tests/unit/core/test_command_backend.py 1 1
tests/unit/core/test_job_manager_edges.py 2 2
tests/unit/core/test_jobs_cgroup_integration.py 3 3
tests/unit/core/test_os_independence_paths.py 1 1
tests/unit/core/test_os_job_partial_persistence.py 2 2
tests/unit/core/test_platform_activation.py 3 3
tests/unit/core/test_process_contract.py 1 2
tests/unit/core/test_runtime_paths.py 2 2
tests/unit/core/test_units.py 1 1
"""
for _row in _T0A9_PIN_TABLE.strip().splitlines():
    _path, _n_uses, _n_nodes = _row.split()
    LINUX_PIN_USE_COUNTS[_path] = int(_n_uses)
    LINUX_PIN_NODE_COUNTS[_path] = int(_n_nodes)
LINUX_PIN_TOTAL_NODES = 182


def _repo_sources() -> dict[str, str]:
    return {
        p.relative_to(ROOT).as_posix(): p.read_text()
        for p in (ROOT / "tests").rglob("*.py")
    }


def test_linux_alias_use_counts_are_pinned_per_file():
    sel = _selection_module()
    assert set(LINUX_PIN_USE_COUNTS) == {*sel.LINUX_PIN_FILES, *sel.T0A9_PIN_FILES}
    assert sum(LINUX_PIN_NODE_COUNTS.values()) == LINUX_PIN_TOTAL_NODES
    problems = sel.check_skip_policy(
        _repo_sources(),
        counts=sel.PLATFORM_SITE_COUNTS,
        alias_uses=LINUX_PIN_USE_COUNTS,
    )
    assert problems == []


def test_reusing_the_linux_alias_on_another_test_fails_the_policy():
    """Negative: an extra @LINUX_ONLY in a pinned file needs a reviewable edit."""
    sel = _selection_module()
    rel = "tests/contracts/test_descriptions.py"
    sources = _repo_sources()
    sources[rel] += "\n\n@LINUX_ONLY\ndef test_smuggled_linux_pin():\n    pass\n"
    problems = sel.check_skip_policy(
        sources, counts=sel.PLATFORM_SITE_COUNTS, alias_uses=LINUX_PIN_USE_COUNTS
    )
    assert len(problems) == 1 and "LINUX_ONLY uses" in problems[0], problems
    sources[rel] = sources[rel].replace("@LINUX_ONLY\n", "")
    assert sel.check_skip_policy(sources, alias_uses=LINUX_PIN_USE_COUNTS) != []


def test_collected_linux_pin_nodes_match_the_pinned_counts():
    """The expanded pytest nodes carrying the alias (-m skipif) are pinned."""
    cmd = [sys.executable, "-m", "pytest", "--collect-only", "-q", "-m", "skipif"]
    cmd += ["-p", "no:randomly", "-p", "no:cacheprovider", *LINUX_PIN_NODE_COUNTS]
    out = subprocess.run(
        cmd, cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout
    found: dict[str, int] = {}
    for line in out.splitlines():
        if "::" in line:
            found[line.split("::", 1)[0]] = found.get(line.split("::", 1)[0], 0) + 1
    assert found == LINUX_PIN_NODE_COUNTS, out[-2000:]


def test_module_level_linux_only_is_limited_to_the_pinned_job_engine_modules():
    """Negative: a module-level LINUX_ONLY elsewhere is a whole-platform skip."""
    sel = _selection_module()
    rel = "tests/unit/core/test_units.py"
    sources = _repo_sources()
    sources[rel] += "\npytestmark = LINUX_ONLY\n"
    problems = sel.check_skip_policy(sources, counts=sel.PLATFORM_SITE_COUNTS)
    assert any("whole-module skip is forbidden" in p for p in problems), problems
    assert all(
        sel.scan_skips(sources[m]) and sel.whole_module_skips(sources[m])
        for m in sel.LINUX_ONLY_MODULES
    )
