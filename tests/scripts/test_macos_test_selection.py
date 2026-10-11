"""Selection rules for native macOS runs: skips must stay narrow and justified.

A Mac run that collects but skips a whole platform looks green while proving
nothing. These tests pin the only Linux-only/opt-in skips in the suite, and
exercise the "falsely green" detector on synthetic pytest output.
"""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Every skip marker whose condition inspects the OS or an opt-in environment,
# with the owned reason. A new entry needs a review; blanket skips never fit.
ALLOWED_PLATFORM_SKIPS = {
    "tests/system/test_uplink_network.py": "Linux SO_BINDTODEVICE / iproute2 only",
    "tests/live/test_deployment_smoke.py": "opt-in live host (BINNACLE_LIVE=1)",
}
PLATFORM_WORDS = ("sys.platform", "platform.system", "os.name")


def parse_summary(output: str) -> dict[str, int]:
    """Counts from a pytest terminal summary line, e.g. '3 passed, 2 skipped'."""
    counts: dict[str, int] = {}
    for number, word in re.findall(
        r"(\d+) (passed|failed|skipped|error|errors)\b", output
    ):
        counts[word.rstrip("s") if word == "errors" else word] = int(number)
    return counts


def falsely_green(output: str, *, exit_code: int) -> bool:
    """A zero-exit run that executed nothing (all skipped, or nothing passed)."""
    counts = parse_summary(output)
    return exit_code == 0 and counts.get("passed", 0) == 0


def _skipif_conditions(tree: ast.AST) -> list[str]:
    found = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "skipif"
            and node.args
        ):
            found.append(ast.unparse(node.args[0]))
    return found


def test_falsely_green_detector_flags_all_skipped_platform():
    assert falsely_green("== 12 skipped in 0.05s ==", exit_code=0)
    assert falsely_green("== no tests ran in 0.01s ==", exit_code=0)
    assert not falsely_green("== 12 passed, 1 skipped in 1.00s ==", exit_code=0)
    assert not falsely_green("== 1 failed in 0.1s ==", exit_code=1)


def test_parse_summary_counts():
    assert parse_summary("== 2 failed, 5 passed, 3 skipped in 1s ==") == {
        "failed": 2,
        "passed": 5,
        "skipped": 3,
    }


def test_platform_conditioned_skips_are_only_the_reviewed_linux_only_set():
    seen = {}
    for path in (ROOT / "tests").rglob("*.py"):
        if path == Path(__file__).resolve():
            continue
        tree = ast.parse(path.read_text())
        hits = [
            c for c in _skipif_conditions(tree) if any(w in c for w in PLATFORM_WORDS)
        ]
        if hits:
            seen[path.relative_to(ROOT).as_posix()] = hits
    assert seen == {
        "tests/system/test_uplink_network.py": ["sys.platform != 'linux'"],
        # Owned Darwin-only host probe; the rest of that module runs everywhere.
        "tests/scripts/test_macos_collection_native.py": ["sys.platform != 'darwin'"],
    }


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


def test_allowed_skip_table_names_existing_files_with_reasons():
    for rel, reason in ALLOWED_PLATFORM_SKIPS.items():
        assert (ROOT / rel).is_file(), rel
        assert reason
