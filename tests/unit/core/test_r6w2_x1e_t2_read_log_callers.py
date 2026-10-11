"""Only the snapshot helpers and the backends touch the raw log primitives.

r6 W2 X1e-t2 (RX1E-N1): ``read_log`` and ``read_log_range`` stay unclamped
protocol primitives. A reply's text and its byte count describe one snapshot
only when the read goes through ``read_log_snapshot`` or
``read_log_range_snapshot`` in ``command_contracts``. A Commands caller that
reads the backend log directly silently loses that pairing, so this AST rule
forbids it everywhere under ``features/commands/`` (``tools/`` and
``job_awareness/`` included) except the classified sites below.
"""

import ast
from pathlib import Path

import pytest

COMMANDS = Path(__file__).resolve().parents[3] / "src/binnacle/features/commands"
PRIMITIVES = frozenset({"read_log", "read_log_range"})
NAME_GETTERS = frozenset({"getattr", "attrgetter", "methodcaller"})

# Every legitimate raw-primitive reference, as (module, enclosing function, name).
ALLOWED = {
    # The one-snapshot pairing itself: each helper reads once and clamps.
    "command_contracts.py": {
        ("read_log_snapshot", "read_log"),
        ("read_log_range_snapshot", "read_log_range"),
    },
    # Backend implementations: each method delegates to the durable store.
    "command_backend.py": {
        ("DurableCommandBackend.read_log", "read_log"),
        ("DurableCommandBackend.read_log_range", "read_log_range"),
        ("DarwinManagerCommandBackend.read_log", "read_log"),
        ("DarwinManagerCommandBackend.read_log_range", "read_log_range"),
    },
    # Backend storage facade: the module functions DurableCommandBackend calls
    # bind the live JOBS_DIR and delegate to job_store; no reply is built here.
    "jobs.py": {
        ("read_log", "read_log"),
        ("read_log_range", "read_log_range"),
    },
}


def raw_log_references(source):
    """(enclosing function, name) for each way the source reaches a primitive."""
    found = []

    def visit(node, scope):
        for child in ast.iter_child_nodes(node):
            inner = scope
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                inner = f"{scope}.{child.name}" if scope else child.name
            name = None
            if isinstance(child, ast.Attribute) and child.attr in PRIMITIVES:
                name = child.attr  # x.read_log(...) and bound-method aliases
            elif (
                isinstance(child, ast.Name)
                and child.id in PRIMITIVES
                and isinstance(child.ctx, ast.Load)
            ):
                name = child.id  # a bare call after `from ... import read_log`
            elif isinstance(child, ast.alias) and (
                child.name.rsplit(".", 1)[-1] in PRIMITIVES
            ):
                name = child.name.rsplit(".", 1)[-1]
            elif isinstance(child, ast.Call):
                func = child.func
                getter = (
                    func.id
                    if isinstance(func, ast.Name)
                    else func.attr
                    if isinstance(func, ast.Attribute)
                    else None
                )
                literals = [
                    arg.value
                    for arg in child.args
                    if isinstance(arg, ast.Constant) and arg.value in PRIMITIVES
                ]
                if getter in NAME_GETTERS and literals:
                    name = literals[0]  # getattr(x, "read_log") and friends
            if name is not None:
                found.append((scope or "<module>", name))
            visit(child, inner)

    visit(ast.parse(source), "")
    return found


def commands_modules():
    return sorted(
        path.relative_to(COMMANDS).as_posix() for path in COMMANDS.rglob("*.py")
    )


def test_scope_covers_commands_tools_and_job_awareness():
    modules = commands_modules()
    assert "command_status.py" in modules
    assert "tools/job_status.py" in modules
    assert any(module.startswith("job_awareness/") for module in modules)
    assert set(ALLOWED) <= set(modules)


@pytest.mark.parametrize("module", commands_modules())
def test_no_direct_raw_log_reads_outside_snapshot_helpers_and_backends(module):
    found = raw_log_references((COMMANDS / module).read_text())
    allowed = ALLOWED.get(module, set())
    assert [site for site in found if site not in allowed] == []


@pytest.mark.parametrize("module", sorted(ALLOWED))
def test_allowed_sites_still_exist(module):
    found = set(raw_log_references((COMMANDS / module).read_text()))
    assert found == ALLOWED[module]


@pytest.mark.parametrize(
    "source",
    [
        "def f(backend, j):\n    return backend.read_log(j)",
        "def f(backend, j):\n    return backend.read_log_range(j, 0, 10)",
        "def f(self, j):\n    return self.backend.read_log(j)",
        "def f(backend, j):\n    read = backend.read_log\n    return read(j)",
        "def f(backend, j):\n    return getattr(backend, 'read_log')(j)",
        "def f(backend, j):\n    return getattr(backend, 'read_log_range')(j, 0, 1)",
        "from operator import methodcaller\nm = methodcaller('read_log', 'j')",
        "import operator\nm = operator.attrgetter('read_log_range')",
        "from binnacle.features.commands.jobs import read_log\nread_log('j')",
        "from binnacle.features.commands import job_store\njob_store.read_log(r, 'j')",
    ],
)
def test_rule_rejects_direct_and_dynamic_reads(source):
    assert raw_log_references(source)


@pytest.mark.parametrize(
    "source",
    [
        "def f(b, j, s):\n    return read_log_snapshot(b, j, s)",
        "def f(b, j, s):\n    return read_log_range_snapshot(b, j, 0, 10, s)",
        "from binnacle.features.commands.command_contracts import read_log_snapshot",
        "log.info('read_log_ms=%.2f', 1.0)",
        "def f(b):\n    return getattr(b, 'log_bytes', None)",
        "class Backend:\n    def read_log(self, job_id):\n        return b''",
    ],
)
def test_rule_accepts_snapshot_helpers_and_definitions(source):
    assert raw_log_references(source) == []
