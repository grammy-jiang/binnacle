"""Test-only compatibility for direct synthetic calls and hostile value fixtures."""

import ast
from pathlib import Path

from fastmcp.tools.base import ToolResult

import binnacle.mcp.job_awareness_hint as adapter
from binnacle.mcp.job_awareness_hint import HintAdapter


class SyntheticHintAdapter(HintAdapter):
    """Direct calls have one unversioned producer; middleware supplies identity."""

    async def adapt(
        self,
        original: ToolResult,
        *,
        tool_name: object = "synthetic",
        tool_version: object = None,
    ) -> ToolResult:
        return await super().adapt(
            original, tool_name=tool_name, tool_version=tool_version
        )


def assert_adapter_import_topology():
    """Feature imports, even TYPE_CHECKING imports, would restore the cycle."""

    files = Path(adapter.__file__).parent.glob("job_awareness_hint*.py")
    tree = ast.Module(
        body=[node for path in files for node in ast.parse(path.read_text()).body],
        type_ignores=[],
    )
    modules = [
        name
        for node in ast.walk(tree)
        for name in (
            [node.module or ""]
            if isinstance(node, ast.ImportFrom)
            else [alias.name for alias in node.names]
            if isinstance(node, ast.Import)
            else []
        )
    ]
    assert not any(name.startswith("binnacle.features") for name in modules)  # nosec B101 - pytest assertion
    assert not any(name.startswith("importlib") for name in modules)  # nosec B101 - pytest assertion
    assert not any(  # nosec B101 - pytest assertion
        isinstance(n, ast.Name) and n.id == "__import__" for n in ast.walk(tree)
    )


def callback_trap():
    calls = []

    class Meta(type):
        def __eq__(cls, other):
            calls.append("metaclass equality")
            return other is dict

        __hash__ = type.__hash__

    class Trap(dict, metaclass=Meta):
        def __len__(self):
            calls.append("length")
            return 0

        def __bool__(self):
            calls.append("truthiness")
            return False

        def get(self, *args):
            calls.append("get")
            return super().get(*args)

    return calls, Trap()
