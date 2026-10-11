"""Selection rules for native macOS runs: skips must stay narrow and justified.

A Mac run that collects but skips a whole platform looks green while proving
nothing. The skip scanner below finds every pytest skip site in ``tests/``
(``skip``/``skipif`` marks, including ones reached through an alias variable or
``pytestmark``, module-level ``pytest.skip`` and in-body ``pytest.skip``), and
the policy enforces the ``ALLOWED_PLATFORM_SKIPS`` table instead of a frozen
snapshot, so lanes that add narrow Darwin-only skips only need a table row.
"""

import ast
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DARWIN_DIR = "tests/platform/darwin/"
OWNER_REASON = re.compile(r"^(A\d|B0|E0|T0|baseline): \S.*")

# Every file that may hold a platform-conditioned or opt-in skip, with the
# owned reason ("<lane>: <why>"). Rows under tests/platform/darwin/ may name a
# file that has not merged yet; every other row must exist. A new row needs a
# review; a whole-module skip never fits here (see ``check_skip_policy``).
ALLOWED_PLATFORM_SKIPS = {
    "tests/system/test_uplink_network.py": (
        "baseline: Linux SO_BINDTODEVICE / iproute2 only"
    ),
    "tests/live/test_deployment_smoke.py": (
        "baseline: opt-in live host (BINNACLE_LIVE=1)"
    ),
    "tests/scripts/test_macos_collection_native.py": (
        "T0: Darwin host probe (sw_vers); the rest of the module runs everywhere"
    ),
    "tests/platform/darwin/test_foreground_commands.py": (
        "A2: per-test Darwin posix_spawn owned-child mechanism"
    ),
    "tests/platform/darwin/test_process_native.py": (
        "A2: per-test Darwin kqueue/posix_spawn child and witness probes"
    ),
    "tests/platform/darwin/test_ipc_generation.py": (
        "A3: per-test Darwin getpeereid/LOCAL_PEERPID contract"
    ),
    "tests/platform/darwin/test_ipc_launchd.py": (
        "A3: per-test opt-in real launchd bootstrap (BINNACLE_A3_LAUNCHD=1)"
    ),
    "tests/platform/darwin/test_search_parity.py": (
        "A4: in-body skip when APFS rejects a non-UTF-8 filename"
    ),
    "tests/platform/darwin/test_package_install.py": (
        "A6: per-test Apple-silicon (arm64) native package install"
    ),
    "tests/platform/darwin/test_composition_contract.py": (
        "B0: in-body skip of the real-socket peer check off Darwin"
    ),
}
PLATFORM_PATTERN = re.compile(
    r"sys\.platform|platform\.|os\.name|\bdarwin\b|\blinux\b|\bmacos\b",
    re.IGNORECASE,
)
MARK_NAMES = {"pytest.mark.skip": "skip", "pytest.mark.skipif": "skipif"}
CALL_NAMES = {"pytest.skip"}


@dataclass(frozen=True)
class SkipSite:
    line: int
    kind: str  # "mark" | "call"
    scope: str  # "module" skips the whole file, "local" a test/class/branch
    condition: str  # "" when unconditional
    platform: bool


_Mark = ast.Call | ast.Attribute


class _Scanner:
    def __init__(self, tree: ast.Module) -> None:
        self.imports: dict[str, str] = {}
        self.values: dict[str, ast.expr] = {}
        self.aliases: dict[str, list[_Mark]] = {}
        self.sites: dict[int, SkipSite] = {}
        self.module_nodes: set[int] = set()
        self._collect_imports(tree)
        self._collect_module_names(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets
            ):
                module_level = id(node) in self._module_assigns
                for mark in self._marks(node.value):
                    self._record_mark(mark, module=module_level)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                for deco in node.decorator_list:
                    for mark in self._marks(deco):
                        self._record_mark(mark, module=False)
            if isinstance(node, ast.Call) and self._mark_kind(node.func):
                self._record_mark(node, module=False)
        self._visit_calls(tree.body, [], in_scope=False, autouse=False)

    # -- name resolution -------------------------------------------------
    def _collect_imports(self, tree: ast.Module) -> None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name == "pytest":
                        self.imports[a.asname or "pytest"] = "pytest"
            elif isinstance(node, ast.ImportFrom) and node.module == "pytest":
                for a in node.names:
                    self.imports[a.asname or a.name] = f"pytest.{a.name}"

    def _collect_module_names(self, tree: ast.Module) -> None:
        self._module_assigns: set[int] = set()
        for node in _module_statements(tree.body):
            if isinstance(node, ast.Assign):
                self._module_assigns.add(id(node))
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.values[target.id] = node.value
                        found = self._marks(node.value)
                        if found:
                            self.aliases[target.id] = found

    def _dotted(self, node: ast.AST) -> str:
        parts: list[str] = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if not isinstance(node, ast.Name):
            return ""
        head = self.imports.get(node.id, node.id)
        return ".".join([head, *reversed(parts)])

    def _mark_kind(self, func: ast.AST) -> str:
        return MARK_NAMES.get(self._dotted(func), "")

    def _marks(self, expr: ast.AST) -> list[_Mark]:
        """Skip-mark nodes an expression resolves to (lists and aliases too)."""
        if isinstance(expr, (ast.List, ast.Tuple, ast.Set)):
            return [m for e in expr.elts for m in self._marks(e)]
        if isinstance(expr, ast.Name):
            return list(self.aliases.get(expr.id, []))
        if isinstance(expr, ast.Call) and self._mark_kind(expr.func):
            return [expr]
        if isinstance(expr, ast.Attribute) and self._mark_kind(expr):
            return [expr]
        return []

    # -- conditions ------------------------------------------------------
    def _text(self, expr: ast.AST | None, depth: int = 3) -> str:
        if expr is None:
            return ""
        text = ast.unparse(expr)
        if depth:
            for name in {n.id for n in ast.walk(expr) if isinstance(n, ast.Name)}:
                if name in self.values:
                    text += " " + self._text(self.values[name], depth - 1)
        return text

    def _record_mark(self, node: _Mark, *, module: bool) -> None:
        func = node.func if isinstance(node, ast.Call) else node
        kind = self._mark_kind(func)
        condition = ""
        if kind == "skipif" and isinstance(node, ast.Call):
            expr = node.args[0] if node.args else None
            for kw in node.keywords:
                if kw.arg == "condition":
                    expr = kw.value
            condition = self._text(expr)
        site = SkipSite(
            node.lineno,
            "mark",
            "module" if module else "local",
            condition,
            bool(PLATFORM_PATTERN.search(condition)),
        )
        previous = self.sites.get(id(node))
        if previous is None or module:
            self.sites[id(node)] = site

    def _visit_calls(
        self, body: list[ast.stmt], conds: list[str], *, in_scope: bool, autouse: bool
    ) -> None:
        for stmt in body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fixture = any(
                    self._dotted(d.func if isinstance(d, ast.Call) else d)
                    == "pytest.fixture"
                    and isinstance(d, ast.Call)
                    and any(
                        k.arg == "autouse"
                        and isinstance(k.value, ast.Constant)
                        and k.value.value is True
                        for k in d.keywords
                    )
                    for d in stmt.decorator_list
                )
                self._visit_calls(
                    stmt.body,
                    [],
                    in_scope=True,
                    autouse=fixture and not in_scope,
                )
                continue
            if isinstance(stmt, ast.ClassDef):
                self._visit_calls(stmt.body, [], in_scope=True, autouse=False)
                continue
            inner = conds
            if isinstance(stmt, (ast.If, ast.While)):
                inner = [*conds, self._text(stmt.test)]
            for child in ast.iter_child_nodes(stmt):
                for call in ast.walk(child) if not isinstance(child, ast.stmt) else []:
                    self._maybe_skip_call(call, inner, in_scope, autouse)
            for field in ("body", "orelse", "finalbody", "handlers"):
                nested = getattr(stmt, field, None)
                if isinstance(nested, list):
                    stmts = [
                        s
                        for item in nested
                        for s in (
                            item.body if isinstance(item, ast.ExceptHandler) else [item]
                        )
                    ]
                    self._visit_calls(stmts, inner, in_scope=in_scope, autouse=autouse)

    def _maybe_skip_call(
        self, call: ast.AST, conds: list[str], in_scope: bool, autouse: bool
    ) -> None:
        if not (isinstance(call, ast.Call) and self._dotted(call.func) in CALL_NAMES):
            return
        condition = " and ".join(c for c in conds if c)
        self.sites[id(call)] = SkipSite(
            call.lineno,
            "call",
            "local" if in_scope and not autouse else "module",
            condition,
            bool(PLATFORM_PATTERN.search(condition)),
        )


def _module_statements(body: list[ast.stmt]) -> Iterator[ast.stmt]:
    """Statements that run at import: top level, inside ``if``/``try`` too."""
    for stmt in body:
        yield stmt
        if isinstance(stmt, (ast.If, ast.Try)):
            for field in ("body", "orelse", "finalbody"):
                yield from _module_statements(getattr(stmt, field, []))
            for handler in getattr(stmt, "handlers", []):
                yield from _module_statements(handler.body)


def scan_skips(source: str) -> list[SkipSite]:
    """Every pytest skip site in a module's source, sorted by line."""
    scanner = _Scanner(ast.parse(source))
    return sorted(scanner.sites.values(), key=lambda s: (s.line, s.kind))


def whole_module_skips(source: str) -> list[SkipSite]:
    """Sites that skip every test in the module (the false-green shape)."""
    return [s for s in scan_skips(source) if s.scope == "module"]


def check_skip_policy(
    sources: Mapping[str, str],
    table: Mapping[str, str] = ALLOWED_PLATFORM_SKIPS,
    *,
    exists: Mapping[str, bool] | None = None,
) -> list[str]:
    """Violations of the skip policy for ``{posix_path: source}``; [] is clean."""
    problems: list[str] = []
    for rel, reason in table.items():
        if not OWNER_REASON.match(reason):
            problems.append(f"{rel}: reason must start with '<owner>: ' ({reason!r})")
        present = rel in sources if exists is None else exists.get(rel, False)
        if not present and not rel.startswith(DARWIN_DIR):
            problems.append(f"{rel}: table row names a missing file")
    for rel, source in sorted(sources.items()):
        sites = scan_skips(source)
        for site in sites:
            where = f"{rel}:{site.line}"
            if site.scope == "module" and (
                site.platform or not site.condition or rel.startswith(DARWIN_DIR)
            ):
                problems.append(f"{where}: whole-module skip is forbidden")
            elif site.platform and rel not in table:
                problems.append(
                    f"{where}: platform-conditioned skip needs an "
                    "ALLOWED_PLATFORM_SKIPS row with an owned reason"
                )
    return problems


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


def _repo_sources() -> dict[str, str]:
    return {
        path.relative_to(ROOT).as_posix(): path.read_text()
        for path in (ROOT / "tests").rglob("*.py")
    }


# -- summary detector ------------------------------------------------------


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


# -- repository policy -----------------------------------------------------


def test_repository_skips_satisfy_the_allowed_platform_skip_table():
    assert check_skip_policy(_repo_sources()) == []


def test_every_existing_table_row_is_owned_and_names_a_real_file():
    sources = _repo_sources()
    for rel, reason in ALLOWED_PLATFORM_SKIPS.items():
        assert OWNER_REASON.match(reason), rel
        if not rel.startswith(DARWIN_DIR):
            assert rel in sources, rel


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
