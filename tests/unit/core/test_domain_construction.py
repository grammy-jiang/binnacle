"""Bounded G2 construction checks, not a settings or provider framework."""

import ast
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[3] / "src" / "binnacle"
MIGRATED = (
    "features/files/paths.py",
    "features/files/tools/read_file.py",
    "features/files/tools/list_files.py",
    "features/files/tools/edit_file.py",
    "features/files/tools/write_file.py",
    "features/search/tools/search_text.py",
    "features/commands/tools/run_command.py",
    "features/commands/tools/job_status.py",
    "features/commands/tools/stop_job.py",
)
COMPOSITION = (
    "server.py",
    "features/files/files_server.py",
    "features/search/search_server.py",
    "features/commands/commands_server.py",
    "visibility.py",
    "logging_middleware.py",
)


class Initialization(ast.NodeVisitor):
    """Visit evaluated initialization expressions, excluding callable bodies."""

    def __init__(self):
        self.calls = []

    def visit_Call(self, node):
        self.calls.append(node)
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        for value in (
            *node.decorator_list,
            *node.args.defaults,
            *node.args.kw_defaults,
            node.returns,
        ):
            if value is not None:
                self.visit(value)
        for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
            if arg.annotation is not None:
                self.visit(arg.annotation)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node):
        for value in (*node.args.defaults, *node.args.kw_defaults):
            if value is not None:
                self.visit(value)


def settings_captures(source):
    tree = ast.parse(source)
    modules, loaders = {"binnacle.config"}, set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name == "binnacle.config"
            )
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if node.module == "binnacle.config" and alias.name == "get_settings":
                    loaders.add(alias.asname or alias.name)
                if node.module == "binnacle" and alias.name == "config":
                    modules.add(alias.asname or alias.name)
    loaders.update(f"{module}.get_settings" for module in modules)
    # Aliases do not make an initialization-time capture acceptable.
    assignments = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)]
    for _ in assignments:
        for node in assignments:
            if ast.unparse(node.value) in loaders:
                loaders.update(ast.unparse(target) for target in node.targets)
    visitor = Initialization()
    visitor.visit(tree)
    return [node.lineno for node in visitor.calls if ast.unparse(node.func) in loaders]


@pytest.mark.parametrize("relative", MIGRATED)
def test_migrated_modules_do_not_capture_settings_at_import(relative):
    assert settings_captures((SOURCE / relative).read_text()) == []


@pytest.mark.parametrize(
    "capture",
    [
        "VALUE = load()",
        "alias = load\nVALUE = alias()",
        "def adapter(value=load()): pass",
        "def adapter(*, value=load()): pass",
        "class Adapter:\n    value = load()",
        "adapter = lambda value=load(): value",
        "@load()\ndef adapter(): pass",
    ],
)
def test_capture_check_includes_aliases_defaults_and_decorators(capture):
    assert settings_captures(
        "from binnacle.config import get_settings as load\n" + capture
    )


def test_capture_check_resolves_config_alias_and_allows_runtime_fallbacks():
    assert settings_captures(
        "from binnacle import config as cfg\nload = cfg.get_settings\nx = load()"
    )
    assert (
        settings_captures("""
from binnacle.config import get_settings
CONSTANT = 100
def adapter(settings=None):
    return get_settings() if settings is None else settings
""")
        == []
    )


@pytest.mark.parametrize("relative", (*MIGRATED, *COMPOSITION))
def test_g2_uses_no_new_runtime_scope_or_provider_mechanism(relative):
    tree = ast.parse((SOURCE / relative).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "fastmcp"
        ):
            assert ".providers" not in node.module
            assert not {alias.name for alias in node.names} & {"Depends", "Provider"}
        if isinstance(node, ast.Call):
            assert all(keyword.arg != "lifespan" for keyword in node.keywords)
        if isinstance(node, ast.Attribute):
            assert node.attr not in {
                "_visibility_rules",
                "_set_visibility",
                "enable_components",
                "disable_components",
            }
