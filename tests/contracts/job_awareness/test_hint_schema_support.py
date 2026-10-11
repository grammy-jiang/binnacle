"""Test-only compatibility for direct synthetic calls and hostile value fixtures."""

import ast
from pathlib import Path

from fastmcp.tools.base import ToolResult

import binnacle.mcp.job_awareness_hint as adapter
from binnacle.mcp import job_awareness_hint_identity as identity
from binnacle.mcp.job_awareness_hint import HintAdapter

_BOUND = object()


def executed(result: object, tool: object) -> identity.Execution:
    """Test fixture: register a receipt for ``result`` naming ``tool``.

    Production receipts come only from witnessed_call after a witnessed body
    completed. In-process code is trusted, so direct tests may register one
    here to drive the adapter's own identity and exact-type checks with
    arbitrary producer objects. This is not a bypass the adapter defends.
    """
    receipt = identity.Execution(tool, result)  # type: ignore[arg-type]
    with identity._LOCK:
        identity._ISSUED.add(receipt)
    return receipt


class SyntheticHintAdapter(HintAdapter):
    """Direct calls model a receipt for the bound Tool object.

    Server-composed tests call HintAdapter.adapt through ExecutionCarrier with
    the receipt witnessed_call issues; only direct calls use this shim.
    """

    async def adapt(  # type: ignore[override]
        self, original: ToolResult, *, tool: object = _BOUND
    ) -> ToolResult:
        producer = self.tool if tool is _BOUND else tool
        return await super().adapt(original, execution=executed(original, producer))


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
