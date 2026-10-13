"""SD-90 (E1-a6): the start-up import module's pinned dynamic-import exemption.

``binnacle.startup_imports`` is the ONE module the G3 scan lets use importlib,
and only as ``importlib.import_module(name)`` inside ``_required_import(name)``,
whose name comes from a frozen binnacle constant: the server's generated
literal ``SERVER_MODULES`` (``binnacle.startup_server_modules``),
``MANAGER_MODULES`` or the empty ``OPTIONAL_MODULES``. The helpers are those of
test_platform_architecture; this module keeps that one under the size limit.
"""

import ast
from pathlib import Path

import pytest

from tests.unit.core.test_platform_architecture import (
    DYNAMIC_IMPORT_EXEMPTIONS,
    EDGES,
    SOURCE,
    violations,
)

WALKS = {
    "pkgutil",
    "iter_modules",
    "walk_packages",
    "listdir",
    "scandir",
    "iterdir",
    "glob",
    "rglob",
    "walk",
}


def test_sd90_dynamic_import_exemption_is_pinned_to_startup_imports_only():
    assert set(DYNAMIC_IMPORT_EXEMPTIONS) == {"startup_imports"}
    assert "SD-90" in DYNAMIC_IMPORT_EXEMPTIONS["startup_imports"]
    for owner in set(EDGES) - set(DYNAMIC_IMPORT_EXEMPTIONS):
        assert "importlib" in violations("import importlib", owner)
    assert EDGES["startup_server_modules"] == set()  # the literal imports nothing
    assert EDGES["startup_imports"] == {"provenance", "startup_server_modules"}


@pytest.mark.parametrize(
    "source",
    [
        "from binnacle.features.search import search_server",
        "from binnacle.platform.darwin import job_manager_entry",
        "from binnacle.platform import composition",
        "from binnacle import server",
        "import binnacle.server",
        "from binnacle.config import get_settings",
        "from importlib import import_module",
        "import importlib.util",
        "import importlib as il",
        "import importlib; importlib.reload(importlib)",
        (
            "import importlib\n"
            "def _required_import(name):\n    return importlib.import_module('x')"
        ),
        (
            "import importlib\n"
            "def _required_import(name):\n    return importlib.import_module(name)\n"
            "def other():\n    return _required_import('binnacle.server')"
        ),
        (
            "import importlib\n"
            "def _required_import(name):\n    return importlib.import_module(name)\n"
            "def _walk(info):\n    return _required_import(info.name)"
        ),
        (
            "import importlib, os\n"
            "def _required_import(name):\n    return importlib.import_module(name)\n"
            "def _fail_fast(process, names_of, system, on_failure):\n"
            "    names = os.environ['X'].split()\n"
            "    for name in names:\n        _required_import(name)"
        ),
        (
            "def _fail_fast(process, names_of, system, on_failure):\n    pass\n"
            "def f():\n    return _fail_fast('p', lambda s: ('binnacle.server',), None, None)"
        ),
    ],
)
def test_sd90_startup_imports_still_rejects_forbidden_edges(source):
    assert violations(source, "startup_imports")


@pytest.mark.parametrize(
    "source",
    [
        "import importlib",
        "from binnacle.config import get_settings",
        "from binnacle.features.files import files_server",
        "import binnacle.server",
    ],
)
def test_sd90_the_generated_literal_module_imports_nothing(source):
    assert violations(source, "startup_server_modules")


def _literal_built(node, constants):
    """A value built only from literals, pinned constants, tuple() and sorted()."""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.Tuple, ast.List)):
        return all(_literal_built(element, constants) for element in node.elts)
    if isinstance(node, ast.Starred):
        return _literal_built(node.value, constants)
    if isinstance(node, ast.Dict):
        return all(
            _literal_built(part, constants) for part in [*node.keys, *node.values]
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _literal_built(node.left, constants) and _literal_built(
            node.right, constants
        )
    if isinstance(node, ast.Name):
        return node.id in constants
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return (
            node.func.id in {"tuple", "sorted"}
            and not node.keywords
            and all(_literal_built(arg, constants) for arg in node.args)
        )
    return False


def _constants(tree, pinned):
    values = {}
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id in pinned:
                    values[target.id] = node.value
    return values


def test_sd90_startup_import_targets_are_frozen_binnacle_constants(monkeypatch):
    """SD-90 criterion 3: every target is a pinned constant of binnacle code
    (the server's generated literal, the manager sets, OPTIONAL_MODULES), never
    config, env, user input or a walk of the installed package directory."""
    tree = ast.parse((SOURCE / "startup_imports.py").read_text())
    literal_tree = ast.parse((SOURCE / "startup_server_modules.py").read_text())
    in_imports = (
        "OPTIONAL_MODULES",
        "_ALWAYS_EXCLUDED",
        "_EXCLUDED_BY_OS",
        "MANAGER_EXCLUDED",
        "_MANAGER_COMMON",
        "MANAGER_MODULES",
    )
    in_literal = (
        "_SERVER_COMMON",
        "_SERVER_EXTRA_LINUX",
        "_SERVER_EXTRA_DARWIN",
        "SERVER_MODULES",
    )
    pinned = {*in_imports, *in_literal}
    values = _constants(tree, in_imports)
    literals = _constants(literal_tree, in_literal)
    assert set(values) == set(in_imports) and set(literals) == set(in_literal)
    for name, value in {**values, **literals}.items():
        assert _literal_built(value, pinned), name
    assert [  # the generated module holds only these assignments and a docstring
        type(node).__name__ for node in literal_tree.body
    ] == ["Expr", "Assign", "Assign", "Assign", "Assign"]
    functions = {
        node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    assert "_walk" not in functions  # the runtime has no walk of its own
    for name in (
        "runtime_module_names",
        "manager_module_names",
        "_required_import",
        "_fail_fast",
    ):
        used = {
            ast.unparse(node)
            for node in ast.walk(functions[name])
            if isinstance(node, (ast.Name, ast.Attribute))
        }
        assert not {"os", "sys", "environ", "get_settings", "open", "input"} & used
        assert not any("environ" in item or "argv" in item for item in used), name
    everything = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not WALKS & everything and not WALKS & imported  # no package-dir walk

    from binnacle import startup_imports, startup_server_modules

    host = startup_imports.platform.system()
    before = (
        startup_imports.runtime_module_names(),
        startup_imports.manager_module_names(),
    )
    for variable in ("BINNACLE_CONFIG", "XDG_STATE_HOME", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(variable, "/nonexistent/sd90")
    after = (
        startup_imports.runtime_module_names(),
        startup_imports.manager_module_names(),
    )
    assert before == after
    assert before[0] == startup_server_modules.SERVER_MODULES[host]
    assert before[1] == startup_imports.MANAGER_MODULES[host]
    assert startup_imports.OPTIONAL_MODULES == ()
    package = Path(startup_imports.binnacle.__file__).parent
    for name in before[0]:
        assert name.startswith("binnacle.")
        relative = Path(*name.split(".")[1:])
        assert (package / relative).is_dir() or (
            package / relative.with_suffix(".py")
        ).is_file(), name
