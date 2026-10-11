"""Selection rules for native macOS runs: skips must stay narrow and justified.

A Mac run that collects but skips a whole platform looks green while proving
nothing. The AST skip scanner finds every pytest skip site in ``tests/`` (marks,
aliases, ``pytestmark``, ``pytest.skip``/``importorskip``, ``xfail(run=False)``,
conftest ``collect_ignore*``); the policy enforces ``ALLOWED_PLATFORM_SKIPS``
with a pinned platform-site count per row, so a new skip needs a reviewed edit.
"""

import ast
import re
import sys
from collections.abc import Collection, Iterator, Mapping
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
# A condition that names an imported/attribute flag or helper the scanner cannot
# read (``from x import ON_MAC``, ``helpers.ON_MAC``) carries this token: it is
# platform-suspect, so the file needs a row exactly like a visible sys.platform.
UNRESOLVED = "<unresolved-flag>"
PLATFORM_PATTERN = re.compile(
    r"sys\.platform|platform\.|os\.name|os\.uname|\bdarwin\b|\blinux\b"
    r"|\bmacos\b|" + re.escape(UNRESOLVED),
    re.IGNORECASE,
)
MARK_NAMES = {
    "pytest.mark.skip": "skip",
    "pytest.mark.skipif": "skipif",
    "pytest.mark.xfail": "xfail",
}
CALL_NAMES = {"pytest.skip", "pytest.importorskip", "pytest.xfail"}
COLLECT_NAMES = {"collect_ignore", "collect_ignore_glob"}
SAFE_MODULES = set(sys.stdlib_module_names) | {"pytest"}

# Module-level ``pytest.importorskip`` skips the whole file when the module is
# missing, so it is only allowed for a named module that exists on every
# supported platform (never inside tests/platform/darwin/).
ALLOWED_MODULE_IMPORTORSKIPS = {("tests/contracts/test_dependency_pin.py", "tomllib")}
# Per row: how many platform-conditioned (or platform-suspect) skip sites the
# file may hold. Adding another one needs an edit here, a reviewable diff.
PLATFORM_SITE_COUNTS = {
    "tests/system/test_uplink_network.py": 1,
    "tests/live/test_deployment_smoke.py": 0,
    "tests/scripts/test_macos_collection_native.py": 1,
    "tests/platform/darwin/test_foreground_commands.py": 1,
    "tests/platform/darwin/test_process_native.py": 1,
    "tests/platform/darwin/test_ipc_generation.py": 1,
    "tests/platform/darwin/test_ipc_launchd.py": 3,
    "tests/platform/darwin/test_search_parity.py": 1,
    "tests/platform/darwin/test_package_install.py": 1,
    "tests/platform/darwin/test_composition_contract.py": 3,
}


@dataclass(frozen=True)
class SkipSite:
    line: int
    kind: str  # "mark" | "call"
    scope: str  # "module" skips the whole file, "local" a test/class/branch
    condition: str  # "" when unconditional
    platform: bool
    target: str = ""  # module named by ``pytest.importorskip``


_Mark = ast.Call | ast.Attribute


class _Scanner:
    def __init__(self, tree: ast.Module, *, conftest: bool = False) -> None:
        self.imports: dict[str, str] = {}
        self.modules: dict[str, str] = {}
        self.from_names: set[str] = set()
        self.funcs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
        self.values: dict[str, ast.expr] = {}
        self.aliases: dict[str, list[_Mark]] = {}
        self.sites: dict[int, SkipSite] = {}
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
            if isinstance(node, ast.Call) and self._is_skip_mark(node):
                self._record_mark(node, module=False)
        self._visit_calls(tree.body, [], in_scope=False, autouse=False)
        if conftest:
            self._scan_conftest(tree.body, [])

    # -- name resolution -------------------------------------------------
    def _collect_imports(self, tree: ast.Module) -> None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name == "pytest":
                        self.imports[a.asname or "pytest"] = "pytest"
                    self.modules[a.asname or a.name.split(".")[0]] = a.name.split(".")[
                        0
                    ]
            elif isinstance(node, ast.ImportFrom):
                for a in node.names:
                    if node.module == "pytest":
                        self.imports[a.asname or a.name] = f"pytest.{a.name}"
                    elif node.module != "__future__":
                        self.from_names.add(a.asname or a.name)

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
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.funcs[node.name] = node

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

    def _is_skip_mark(self, node: ast.AST) -> bool:
        """A skip/skipif mark, or an xfail that never runs the test."""
        func = node.func if isinstance(node, ast.Call) else node
        kind = self._mark_kind(func)
        if kind != "xfail":
            return bool(kind)
        return isinstance(node, ast.Call) and any(
            kw.arg == "run"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value is False
            for kw in node.keywords
        )

    def _marks(self, expr: ast.AST) -> list[_Mark]:
        """Skip-mark nodes an expression resolves to (lists and aliases too)."""
        if isinstance(expr, (ast.List, ast.Tuple, ast.Set)):
            return [m for e in expr.elts for m in self._marks(e)]
        if isinstance(expr, ast.Name):
            return list(self.aliases.get(expr.id, []))
        if isinstance(expr, (ast.Call, ast.Attribute)) and self._is_skip_mark(expr):
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
                elif name in self.funcs:
                    text += " " + ast.unparse(self.funcs[name])
        if self._suspect(expr, depth):
            text += " " + UNRESOLVED
        return text

    def _suspect(self, expr: ast.AST, depth: int = 3) -> bool:
        """Does the expression use a flag or helper the scanner cannot read?

        True for names bound by ``from x import y`` and for non-stdlib module
        attributes (``helpers.ON_MAC``, ``helpers.on_mac()``); module-level
        constants and helper functions are followed instead.
        """
        inner = {id(n.value) for n in ast.walk(expr) if isinstance(n, ast.Attribute)}
        for n in ast.walk(expr):
            if isinstance(n, ast.Name) and n.id in self.from_names:
                return True
            if isinstance(n, ast.Name) and depth:
                if n.id in self.values and self._suspect(self.values[n.id], depth - 1):
                    return True
                fn = self.funcs.get(n.id)
                if fn is not None and any(
                    r.value is not None and self._suspect(r.value, depth - 1)
                    for r in ast.walk(fn)
                    if isinstance(r, ast.Return)
                ):
                    return True
            if isinstance(n, ast.Attribute) and id(n) not in inner:
                root = n
                while isinstance(root, ast.Attribute):
                    root = root.value  # type: ignore[assignment]
                top = self.modules.get(root.id) if isinstance(root, ast.Name) else None
                if top is not None and top not in SAFE_MODULES:
                    return True
        return False

    def _record_mark(self, node: _Mark, *, module: bool) -> None:
        func = node.func if isinstance(node, ast.Call) else node
        kind = self._mark_kind(func)
        condition = ""
        if kind in ("skipif", "xfail") and isinstance(node, ast.Call):
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
        target = ""
        if self._dotted(call.func) == "pytest.importorskip" and call.args:
            target = ast.unparse(call.args[0]).strip("'\"")
        self.sites[id(call)] = SkipSite(
            call.lineno,
            "call",
            "local" if in_scope and not autouse else "module",
            condition,
            bool(PLATFORM_PATTERN.search(condition)),
            target,
        )

    def _scan_conftest(self, body: list[ast.stmt], conds: list[str]) -> None:
        """Collection-time drops: ``collect_ignore*`` and ``pytest_ignore_collect``."""
        for stmt in body:
            if isinstance(stmt, (ast.If, ast.Try)):
                inner = (
                    [*conds, self._text(stmt.test)]
                    if isinstance(stmt, ast.If)
                    else conds
                )
                for field in ("body", "orelse", "finalbody"):
                    self._scan_conftest(getattr(stmt, field, []), inner)
                for handler in getattr(stmt, "handlers", []):
                    self._scan_conftest(handler.body, inner)
            elif _drops_collection(stmt):
                body_text = (
                    ast.unparse(stmt) if isinstance(stmt, ast.FunctionDef) else ""
                )
                text = " and ".join([*(c for c in conds if c), body_text]).strip()
                platform = bool(PLATFORM_PATTERN.search(text))
                site = SkipSite(stmt.lineno, "collect", "module", text, platform)
                self.sites[id(stmt)] = site


def _drops_collection(stmt: ast.stmt) -> bool:
    hook = COLLECT_NAMES | {"pytest_ignore_collect"}
    if isinstance(stmt, ast.Assign):
        return any(isinstance(t, ast.Name) and t.id in hook for t in stmt.targets)
    if isinstance(stmt, (ast.AnnAssign, ast.AugAssign)):
        return isinstance(stmt.target, ast.Name) and stmt.target.id in hook
    if isinstance(stmt, ast.FunctionDef):
        return stmt.name in hook
    if isinstance(stmt, ast.ImportFrom):
        return any((a.asname or a.name) in hook for a in stmt.names)
    call = stmt.value if isinstance(stmt, ast.Expr) else None
    func = call.func if isinstance(call, ast.Call) else None
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id in COLLECT_NAMES
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


def scan_skips(source: str, *, conftest: bool = False) -> list[SkipSite]:
    """Every pytest skip site in a module's source, sorted by line.

    ``conftest=True`` also reports collection-time drops (``collect_ignore*``
    and ``pytest_ignore_collect``), which remove modules without a skip line.
    """
    scanner = _Scanner(ast.parse(source), conftest=conftest)
    return sorted(scanner.sites.values(), key=lambda s: (s.line, s.kind))


def whole_module_skips(source: str) -> list[SkipSite]:
    """Sites that skip every test in the module (the false-green shape)."""
    return [s for s in scan_skips(source) if s.scope == "module"]


def check_skip_policy(
    sources: Mapping[str, str],
    table: Mapping[str, str] = ALLOWED_PLATFORM_SKIPS,
    *,
    exists: Mapping[str, bool] | None = None,
    counts: Mapping[str, int] | None = None,
    importorskips: Collection[tuple[str, str]] = ALLOWED_MODULE_IMPORTORSKIPS,
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
        sites = scan_skips(source, conftest=rel.rsplit("/", 1)[-1] == "conftest.py")
        platform_sites = 0
        for site in sites:
            where = f"{rel}:{site.line}"
            allowed_import = (rel, site.target) in importorskips
            if site.scope == "module" and (
                site.platform
                or rel.startswith(DARWIN_DIR)
                or (site.target and not allowed_import)
                or (not site.condition and not allowed_import)
            ):
                problems.append(f"{where}: whole-module skip is forbidden")
            elif site.platform and rel not in table:
                problems.append(
                    f"{where}: platform-conditioned skip needs an "
                    "ALLOWED_PLATFORM_SKIPS row with an owned reason"
                )
            platform_sites += site.platform
        if counts is not None and rel in table and platform_sites != counts.get(rel):
            problems.append(
                f"{rel}: {platform_sites} platform skip sites but the row pins "
                f"{counts.get(rel)}; edit PLATFORM_SITE_COUNTS with the row"
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
    assert check_skip_policy(_repo_sources(), counts=PLATFORM_SITE_COUNTS) == []


def test_every_table_row_pins_a_platform_site_count():
    assert set(PLATFORM_SITE_COUNTS) == set(ALLOWED_PLATFORM_SKIPS)


def test_every_existing_table_row_is_owned_and_names_a_real_file():
    sources = _repo_sources()
    for rel, reason in ALLOWED_PLATFORM_SKIPS.items():
        assert OWNER_REASON.match(reason), rel
        if not rel.startswith(DARWIN_DIR):
            assert rel in sources, rel
