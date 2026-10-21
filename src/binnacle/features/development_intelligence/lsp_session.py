"""P2.3: conservative LSP initialize, capability gates, and UTF-16 positions.

No workspace scanning or dirty-buffer synchronization (those belong to P2.5).
Only advertises read-oriented capabilities and rejects unsupported encodings.
"""

from __future__ import annotations

from typing import Any

from .lsp_client import LspClient
from .lsp_wire import LspProtocolError

CAPABILITY_KEYS = {
    "textDocument/definition": "definitionProvider",
    "textDocument/declaration": "declarationProvider",
    "textDocument/typeDefinition": "typeDefinitionProvider",
    "textDocument/implementation": "implementationProvider",
    "textDocument/references": "referencesProvider",
    "textDocument/documentSymbol": "documentSymbolProvider",
    "workspace/symbol": "workspaceSymbolProvider",
    "textDocument/hover": "hoverProvider",
}


def utf16_offset(text: str, index: int) -> int:
    """Python codepoint boundary -> LSP UTF-16 code unit offset."""
    if type(index) is not int or not 0 <= index <= len(text):
        raise ValueError("invalid_unicode_index")
    prefix = text[:index]
    if any(0xD800 <= ord(char) <= 0xDFFF for char in prefix):
        raise ValueError("unpaired_utf16_surrogate")
    return sum(2 if ord(char) > 0xFFFF else 1 for char in prefix)


def python_offset(text: str, character: int) -> int:
    """LSP UTF-16 offset -> Python codepoint boundary (no surrogate splits)."""
    if type(character) is not int or character < 0:
        raise ValueError("invalid_utf16_offset")
    count = 0
    for index, ch in enumerate(text):
        if 0xD800 <= ord(ch) <= 0xDFFF:
            raise ValueError("unpaired_utf16_surrogate")
        if count == character:
            return index
        count += 2 if ord(ch) > 0xFFFF else 1
        if count > character:
            raise ValueError("utf16_offset_splits_codepoint")
    if count == character:
        return len(text)
    raise ValueError("utf16_offset_out_of_range")


class LspSession:
    """Initialize exactly once; deny unsupported/mutating semantic methods."""

    def __init__(self, client: LspClient) -> None:
        self._client = client
        self._capabilities: dict[str, Any] | None = None
        self._closing = False
        self._initialize_attempted = False

    @property
    def initialized(self) -> bool:
        return self._capabilities is not None

    @property
    def capabilities(self) -> dict[str, Any]:
        if self._capabilities is None:
            raise LspProtocolError("lsp_not_initialized")
        return dict(self._capabilities)

    def supports(self, method: str) -> bool:
        if self._capabilities is None:
            return False
        name = CAPABILITY_KEYS.get(method)
        if name is None:
            return False
        capability = self._capabilities.get(name, False)
        return capability is True or isinstance(capability, dict)

    async def initialize(self, *, root_uri: str | None = None) -> dict:
        if self._initialize_attempted or self._closing:
            raise LspProtocolError("lsp_already_initialized_or_closed")
        if root_uri is not None and not (
            isinstance(root_uri, str) and root_uri.startswith("file:///")
        ):
            raise ValueError("root_uri_must_be_file_uri")
        # Only one initialize attempt may occur per protocol connection, even
        # when two callers race or the first initialization fails.
        self._initialize_attempted = True
        params = {
            "processId": None,
            "rootUri": root_uri,
            "capabilities": {
                "general": {"positionEncodings": ["utf-16"]},
                "workspace": {
                    "applyEdit": False,
                    "configuration": True,
                    "workspaceFolders": False,
                    "didChangeConfiguration": {"dynamicRegistration": False},
                },
                "textDocument": {
                    "definition": {"dynamicRegistration": False},
                    "references": {"dynamicRegistration": False},
                    "documentSymbol": {"dynamicRegistration": False},
                    "hover": {"dynamicRegistration": False},
                    "synchronization": {
                        "dynamicRegistration": False,
                        "didSave": False,
                    },
                },
            },
            "clientInfo": {"name": "Binnacle Development Intelligence"},
        }
        result = await self._client.request("initialize", params)
        if not isinstance(result, dict) or not isinstance(
            result.get("capabilities"), dict
        ):
            raise LspProtocolError("malformed_lsp_initialize_result")
        capabilities = result["capabilities"]
        encoding = capabilities.get("positionEncoding", "utf-16")
        if encoding != "utf-16":
            raise LspProtocolError("unsupported_lsp_position_encoding")
        await self._client.notify("initialized", {})
        self._capabilities = dict(capabilities)
        return self.capabilities

    async def request_semantic(self, method: str, params: dict) -> Any:
        if self._capabilities is None:
            raise LspProtocolError("lsp_not_initialized")
        if self._closing:
            raise LspProtocolError("lsp_session_closing")
        if not self.supports(method):
            raise LspProtocolError("lsp_capability_unavailable")
        if not isinstance(params, dict):
            raise TypeError("semantic_params_must_be_object")
        return await self._client.request(method, params)

    async def shutdown(self) -> None:
        if self._closing:
            return
        self._closing = True
        if self._capabilities is not None:
            await self._client.request("shutdown", {})
            await self._client.notify("exit", {})
        # Caller owns aclose/underlying pipes and process (P2.4).
