"""Native collection receipts: default pytest discovery on the running OS.

These tests run real subprocesses (``pytest --collect-only``, ``sw_vers``) with
no mocks. They execute on Linux and macOS; only the Darwin-host probe is
OS-specific and it is skipped solely where ``sys.platform`` is not ``darwin``.
"""

import importlib.util
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


def _selection():
    """The T0 skip scanner and detectors, loaded by path (no package here)."""
    path = ROOT / "tests/scripts/test_macos_test_selection.py"
    spec = importlib.util.spec_from_file_location("_t0_selection", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SEL = _selection()
scan_skips = SEL.scan_skips
whole_module_skips = SEL.whole_module_skips
check_skip_policy = SEL.check_skip_policy
parse_summary = SEL.parse_summary
falsely_green = SEL.falsely_green
ALLOWED_PLATFORM_SKIPS = SEL.ALLOWED_PLATFORM_SKIPS
DARWIN_DIR = SEL.DARWIN_DIR


def _real_pytest(tmp_path: Path, source: str) -> tuple[int, str]:
    """Run real pytest on a throwaway module in an isolated rootdir."""
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / "test_probe.py").write_text(source)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "-q",
            "test_probe.py",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=55,
        check=False,
    )
    return proc.returncode, proc.stdout


# -- real native run receipts (R2P-T0-03) ---------------------------------


def test_falsely_green_on_a_real_all_skipped_native_run(tmp_path):
    code, out = _real_pytest(
        tmp_path,
        "import pytest\n"
        "pytestmark = pytest.mark.skipif(True, reason='whole platform')\n"
        "def test_a(): ...\n"
        "def test_b(): ...\n",
    )
    assert code == 0, out
    assert parse_summary(out) == {"skipped": 2}
    assert falsely_green(out, exit_code=code)


def test_real_run_with_executed_tests_is_not_falsely_green(tmp_path):
    code, out = _real_pytest(
        tmp_path,
        "import pytest\n"
        "def test_a(): ...\n"
        "@pytest.mark.skip(reason='narrow')\n"
        "def test_b(): ...\n",
    )
    assert code == 0, out
    assert parse_summary(out) == {"passed": 1, "skipped": 1}
    assert not falsely_green(out, exit_code=code)


def test_real_run_of_the_darwin_contract_module_is_not_falsely_green():
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "-q",
            "tests/platform/darwin/test_collection_contract.py",
            "-k",
            "not default_discovery",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=55,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert parse_summary(proc.stdout).get("passed", 0) > 0
    assert not falsely_green(proc.stdout, exit_code=proc.returncode)


# -- scanner regressions (R2P-T0-01) ---------------------------------------

ALIAS_SKIPIF = (
    "import pytest, sys\n"
    "NATIVE = pytest.mark.skipif(sys.platform != 'darwin', reason='x')\n"
    "@NATIVE\n"
    "def test_a(): ...\n"
)
BYPASSES = {
    "alias-skipif": ALIAS_SKIPIF,
    "module-pytest-skip": (
        "import pytest, sys\n"
        "if sys.platform != 'darwin':\n"
        "    pytest.skip('x', allow_module_level=True)\n"
        "def test_a(): ...\n"
    ),
    "in-body-skip": (
        "import pytest, sys\n"
        "def test_a():\n"
        "    if sys.platform != 'darwin':\n"
        "        pytest.skip('x')\n"
    ),
    "condition-via-variable": (
        "import pytest, sys\n"
        "ON_MAC = sys.platform == 'darwin'\n"
        "@pytest.mark.skipif(not ON_MAC, reason='x')\n"
        "def test_a(): ...\n"
    ),
    "from-import-alias": (
        "from pytest import mark as m\n"
        "import sys\n"
        "@m.skipif(sys.platform == 'linux', reason='x')\n"
        "def test_a(): ...\n"
    ),
    "string-condition": (
        "import pytest\n"
        "@pytest.mark.skipif('sys.platform != \"darwin\"', reason='x')\n"
        "def test_a(): ...\n"
    ),
    "keyword-condition": (
        "import pytest, platform\n"
        "@pytest.mark.skipif(condition=platform.system() != 'Darwin', reason='x')\n"
        "def test_a(): ...\n"
    ),
}
WHOLE_MODULE = {
    "pytestmark-direct": (
        "import pytest, sys\n"
        "pytestmark = pytest.mark.skipif(sys.platform != 'darwin', reason='x')\n"
    ),
    "pytestmark-list": "import pytest\npytestmark = [pytest.mark.skip(reason='x')]\n",
    "pytestmark-alias": ALIAS_SKIPIF + "pytestmark = NATIVE\n",
    "pytestmark-alias-list": (
        "import pytest, sys\n"
        "N = pytest.mark.skipif(sys.platform != 'darwin', reason='x')\n"
        "pytestmark = [pytest.mark.no_xdist, N]\n"
    ),
    "module-level-call": BYPASSES["module-pytest-skip"],
    "unconditional-module-call": "import pytest\npytest.skip('x', allow_module_level=True)\n",
    "autouse-fixture": (
        "import pytest, sys\n"
        "@pytest.fixture(autouse=True)\n"
        "def _only_mac():\n"
        "    if sys.platform != 'darwin':\n"
        "        pytest.skip('x')\n"
    ),
}


@pytest.mark.parametrize("name", sorted(BYPASSES))
def test_scanner_finds_every_platform_skip_shape(name):
    sites = scan_skips(BYPASSES[name])
    assert any(s.platform for s in sites), sites


@pytest.mark.parametrize("name", sorted(WHOLE_MODULE))
def test_scanner_flags_whole_module_skips(name):
    assert whole_module_skips(WHOLE_MODULE[name]), name


def test_scanner_keeps_narrow_and_non_platform_skips_local():
    source = (
        "import pytest, os\n"
        "pytestmark = pytest.mark.no_xdist\n"
        "@pytest.mark.skipif(os.geteuid() == 0, reason='root')\n"
        "def test_a(): ...\n"
        "def test_b():\n"
        "    pytest.skip('needs nmcli')\n"
        "class TestC:\n"
        "    @pytest.mark.skip(reason='x')\n"
        "    def test_d(): ...\n"
    )
    sites = scan_skips(source)
    assert len(sites) == 3
    assert not whole_module_skips(source)
    assert not any(s.platform for s in sites)


def test_scanner_ignores_a_local_function_that_is_not_pytest_skip():
    assert scan_skips("def skip(x): ...\ndef test_a():\n    skip(1)\n") == []


# -- policy regressions (R2P-T0-01/02, B0-T0-SKIPS) --------------------------

NARROW = (
    "import pytest, sys\n"
    "@pytest.mark.skipif(sys.platform != 'darwin', reason='x')\n"
    "def test_a(): ...\n"
    "def test_b(): ...\n"
)


def test_policy_accepts_listed_narrow_darwin_skips_in_any_merge_order():
    table = {
        **ALLOWED_PLATFORM_SKIPS,
        "tests/platform/darwin/test_future_lane.py": "A9: per-test native probe",
    }
    # A lane that merged brings its file and its row; one that has not merged
    # leaves a Darwin row unmatched. Neither may break the suite.
    merged = {"tests/platform/darwin/test_future_lane.py": NARROW}
    problems = check_skip_policy(merged, table)
    assert problems and all("names a missing file" in p for p in problems)
    assert not any("test_future_lane" in p for p in problems)
    assert not any(p.startswith(DARWIN_DIR) for p in problems)
    assert check_skip_policy({}, {"tests/platform/darwin/test_x.py": "A9: y"}) == []


def test_policy_rejects_an_unlisted_platform_skip_and_a_bad_reason():
    rel = "tests/unit/test_new.py"
    problems = check_skip_policy({rel: NARROW}, {})
    assert len(problems) == 1 and "needs an ALLOWED_PLATFORM_SKIPS row" in problems[0]
    problems = check_skip_policy({}, {"tests/platform/darwin/t.py": "no owner here"})
    assert problems and "reason must start with" in problems[0]


@pytest.mark.parametrize("name", sorted(WHOLE_MODULE))
def test_policy_rejects_whole_module_skips_even_when_listed(name):
    rel = "tests/platform/darwin/test_bad.py"
    problems = check_skip_policy({rel: WHOLE_MODULE[name]}, {rel: "A2: listed anyway"})
    assert any("whole-module skip is forbidden" in p for p in problems), problems


def test_policy_rejects_any_module_level_skip_in_the_darwin_package():
    rel = "tests/platform/darwin/test_env_gated.py"
    source = (
        "import pytest, os\n"
        "pytestmark = pytest.mark.skipif(not os.environ.get('X'), reason='x')\n"
    )
    assert check_skip_policy({rel: source}, {rel: "A2: y"})
    # An opt-in module gate outside the Darwin package is table-governed only.
    assert not check_skip_policy(
        {"tests/live/t.py": source}, {"tests/live/t.py": "baseline: y"}
    )


def test_policy_rejects_unconditional_whole_module_skip_anywhere():
    source = "import pytest\npytestmark = pytest.mark.skip(reason='x')\n"
    assert check_skip_policy({"tests/unit/test_a.py": source}, {})
