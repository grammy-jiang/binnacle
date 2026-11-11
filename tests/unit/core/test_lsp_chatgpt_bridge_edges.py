"""Bridge refusals: invalid setup, unusable credentials, and untrusted replies.

Every failure reaches ChatGPT only as a fixed reason code; provider text, the
private token and protocol errors are never forwarded.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Self

import pytest
from fastmcp import Client

from binnacle.features import lsp_bridge_server as bridge
from tests.unit.core.test_lsp_chatgpt_bridge import _state

TOKEN_MARK = "synthetic-test-secret-"


def test_token_outside_the_length_bounds_is_refused(tmp_path: Path) -> None:
    state = _state(tmp_path)
    (state / "token").write_text("short")
    with pytest.raises(ValueError, match="private_lsp_token_invalid"):
        bridge._credentials(state, tmp_path / "Projects")


def test_workspace_must_be_an_existing_directory(tmp_path: Path) -> None:
    file = tmp_path / "Projects"
    file.write_text("not a directory")
    with pytest.raises(ValueError, match="invalid_lsp_bridge_workspace"):
        bridge.create_lsp_bridge_server(state_dir=tmp_path, workspace=file)


def test_state_dir_must_be_absolute(tmp_path: Path) -> None:
    workspace = tmp_path / "Projects"
    workspace.mkdir()
    with pytest.raises(ValueError, match="invalid_lsp_bridge_state_dir"):
        bridge.create_lsp_bridge_server(
            state_dir=Path("relative-state"), workspace=workspace
        )


def _call(child: Any) -> Any:
    async def run() -> Any:
        async with Client(child) as client:
            return await client.call_tool(
                "inspect_symbol",
                {"path": "demo/a.py", "line": 1, "symbol_text": "x"},
                raise_on_error=False,
            )

    return asyncio.run(run())


def _stub(reply: Any = None, error: Exception | None = None) -> type:
    class StubClient:
        def __init__(self, transport: Any, *, timeout: float) -> None:
            pass

        async def __aenter__(self) -> Self:
            if error is not None:
                raise error
            return self

        async def __aexit__(self, *_args: object) -> bool:
            return False

        async def call_tool(self, name: str, args: dict, *, raise_on_error: bool):
            return reply

    return StubClient


def _bridge(tmp_path: Path) -> Any:
    workspace = tmp_path / "Projects"
    workspace.mkdir()
    return bridge.create_lsp_bridge_server(
        state_dir=_state(tmp_path), workspace=workspace
    )


def _refused(result: Any, code: str) -> None:
    text = " ".join(getattr(item, "text", "") for item in result.content)
    assert result.is_error
    assert code in text
    assert TOKEN_MARK not in text


def test_unreadable_credentials_report_only_unavailable(tmp_path: Path) -> None:
    child = _bridge(tmp_path)
    (tmp_path / "state" / "grants.json").unlink()
    _refused(_call(child), "private_lsp_unavailable")


@pytest.mark.parametrize(
    ("reply", "code"),
    [
        (
            SimpleNamespace(is_error=True, structured_content=None),
            "provider_unavailable",
        ),
        (SimpleNamespace(is_error=False, structured_content=["x"]), "response_invalid"),
        (
            SimpleNamespace(
                is_error=False,
                structured_content={"blob": "x" * (bridge._MAX_RESULT_BYTES + 1)},
            ),
            "response_too_large",
        ),
    ],
)
def test_untrusted_provider_replies_become_fixed_codes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, reply: Any, code: str
) -> None:
    monkeypatch.setattr(bridge, "Client", _stub(reply=reply))
    _refused(_call(_bridge(tmp_path)), f"private_lsp_{code}")


def test_transport_error_text_is_never_forwarded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    secret = RuntimeError(f"connect failed with {TOKEN_MARK}leak and /etc/path")
    monkeypatch.setattr(bridge, "Client", _stub(error=secret))
    result = _call(_bridge(tmp_path))
    _refused(result, "private_lsp_unavailable")
    text = " ".join(getattr(item, "text", "") for item in result.content)
    assert "/etc/path" not in text and "connect failed" not in text
