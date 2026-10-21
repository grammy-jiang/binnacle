"""Optional upstream multilspy adapter for the Pyright Python LSP provider.

No import of multilspy or process startup occurs with Binnacle's default-off
configuration. Call create_pyright_adapter only in an explicitly opted-in,
already-authorized private provider context; P2.4 owns release admission.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urlsplit

Mode = Literal["off", "basic", "standard", "strict"]
DiagnosticScope = Literal["openFilesOnly", "workspace"]


@dataclass(frozen=True)
class PyrightOptions:
    type_checking_mode: Mode = "standard"
    diagnostic_mode: DiagnosticScope = "openFilesOnly"
    initialize_timeout_s: float = 12.0
    shutdown_timeout_s: float = 4.0

    def __post_init__(self) -> None:
        if self.type_checking_mode not in ("off", "basic", "standard", "strict"):
            raise ValueError("invalid_pyright_type_checking_mode")
        if self.diagnostic_mode not in ("openFilesOnly", "workspace"):
            raise ValueError("invalid_pyright_diagnostic_mode")
        if not 0 < self.initialize_timeout_s <= 120:
            raise ValueError("invalid_pyright_initialize_deadline")
        if not 0 < self.shutdown_timeout_s <= 30:
            raise ValueError("invalid_pyright_shutdown_deadline")


def _authorized_file(root: Path, relative: str) -> tuple[str, Path]:
    """Prevent implicit absolute, traversal, symlink and off-root file reads."""
    if not isinstance(relative, str) or not relative or "\x00" in relative:
        raise ValueError("invalid_pyright_source_path")
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("pyright_source_outside_workspace")
    candidate = (root / path).resolve(strict=True)
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise ValueError("pyright_source_outside_workspace")
    return str(candidate.relative_to(root)), candidate


def _result_location(root: Path, entry: Any) -> dict:
    """Normalize LSP Location and spec-valid LocationLink; fail off-root."""
    if not isinstance(entry, dict):
        raise TypeError("invalid_pyright_location")
    uri = entry.get("uri", entry.get("targetUri"))
    span = entry.get("range", entry.get("targetSelectionRange"))
    if not isinstance(uri, str) or not isinstance(span, dict):
        raise TypeError("invalid_pyright_location")
    for endpoint in ("start", "end"):
        position = span.get(endpoint)
        if not isinstance(position, dict) or any(
            type(position.get(field)) is not int or position[field] < 0
            for field in ("line", "character")
        ):
            raise ValueError("invalid_pyright_location_range")
    parsed = urlsplit(uri)
    if (
        parsed.scheme != "file"
        or parsed.netloc not in ("", "localhost")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("unsupported_pyright_result_uri")
    path = Path(unquote(parsed.path)).resolve(strict=False)
    if not path.is_relative_to(root):
        raise ValueError("pyright_result_outside_workspace")
    return {
        "uri": uri,
        "range": span,
        "absolutePath": str(path),
        "relativePath": str(path.relative_to(root)),
    }


def normalize_locations(root: Path, response: Any) -> list[dict]:
    """Treat null as zero results; support single or plural LocationLink."""
    if response is None:
        return []
    entries = response if isinstance(response, list) else [response]
    if len(entries) > 2048:
        raise ValueError("pyright_location_limit")
    return [_result_location(root, item) for item in entries]


def create_pyright_adapter(
    config: Any,
    logger: Any,
    repository_root: str | Path,
    *,
    executable: str | Path,
    options: PyrightOptions | None = None,
) -> Any:
    """Make an upstream LanguageServer subclass, without modifying its factory.

    This method loads multilspy lazily. The executable is an explicit absolute
    host-trusted path, never auto-discovered or downloaded. Domain admission,
    stable binary identities and effective OS confinement are separately gated.
    """
    root = Path(repository_root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("pyright_workspace_not_directory")
    binary = Path(executable).expanduser()
    if not binary.is_absolute() or not binary.exists() or binary.is_dir():
        raise ValueError("pyright_executable_must_be_existing_absolute_path")
    if bool(getattr(config, "trace_lsp_communication", False)):
        raise ValueError("pyright_raw_wire_logging_not_allowed")
    settings = options if options is not None else PyrightOptions()
    if not isinstance(settings, PyrightOptions):
        raise TypeError("invalid_pyright_options")

    # No import-time dependency on multilspy for normal Binnacle clients.
    from multilspy.language_server import LanguageServer
    from multilspy.lsp_protocol_handler.lsp_types import ErrorCodes
    from multilspy.lsp_protocol_handler.server import Error, ProcessLaunchInfo

    class PyrightAdapter(LanguageServer):
        def __init__(self) -> None:
            super().__init__(
                config,
                logger,
                str(root),
                ProcessLaunchInfo(cmd=[str(binary), "--stdio"], cwd=str(root)),
                "python",
            )
            self.capabilities: dict[str, Any] = {}
            self.diagnostics: asyncio.Queue[dict] = asyncio.Queue(maxsize=32)
            self.diagnostics_dropped = False

        @contextmanager
        def open_file(self, relative_file_path: str) -> Iterator[None]:
            safe, _ = _authorized_file(root, relative_file_path)
            with super().open_file(safe):
                yield

        @asynccontextmanager
        async def start_server(self) -> Iterator[Any]:
            async def configuration(params: Any) -> list:
                if not isinstance(params, dict):
                    return []
                items = params.get("items")
                if not isinstance(items, list) or len(items) > 64:
                    return []
                analysis = {
                    "typeCheckingMode": settings.type_checking_mode,
                    "diagnosticMode": settings.diagnostic_mode,
                }
                pyright = {
                    "disableLanguageServices": False,
                    "disableOrganizeImports": True,
                }
                sections = {
                    "python": {"analysis": analysis},
                    "python.analysis": analysis,
                    "pyright": pyright,
                }
                return [
                    sections.get(item.get("section"))
                    if isinstance(item, dict) and isinstance(item.get("section"), str)
                    else None
                    for item in items
                ]

            async def refuse_edit(_params: Any) -> dict:
                return {
                    "applied": False,
                    "failureReason": "Read-only Binnacle Pyright adapter",
                }

            async def refuse_registration(_params: Any) -> None:
                raise Error(ErrorCodes.MethodNotFound, "Dynamic registration disabled")

            async def diagnostics(params: Any) -> None:
                if not isinstance(params, dict) or not isinstance(
                    params.get("uri"), str
                ):
                    return
                if self.diagnostics.full():
                    self.diagnostics_dropped = True
                    return
                self.diagnostics.put_nowait(params)

            async def ignore_notification(_params: Any) -> None:
                return None

            self.server.on_request("workspace/configuration", configuration)
            self.server.on_request("workspace/applyEdit", refuse_edit)
            self.server.on_request("client/registerCapability", refuse_registration)
            self.server.on_notification("textDocument/publishDiagnostics", diagnostics)
            self.server.on_notification("window/logMessage", ignore_notification)
            self.server.on_notification("$/progress", ignore_notification)

            async with super().start_server():
                initialized = False
                try:
                    # An unsuccessful start may still have allocated a child.
                    # Always enter the cleanup path once the lifespan begins.
                    await self.server.start()
                    params = {
                        "processId": None,
                        "rootPath": str(root),
                        "rootUri": root.as_uri(),
                        "workspaceFolders": [{"name": root.name, "uri": root.as_uri()}],
                        "clientInfo": {"name": "Binnacle Pyright Adapter"},
                        "capabilities": {
                            "general": {"positionEncodings": ["utf-16"]},
                            "workspace": {
                                "applyEdit": False,
                                "configuration": True,
                                "workspaceFolders": False,
                                "symbol": {"dynamicRegistration": False},
                                # Rename returns an edit proposal; Binnacle
                                # never applies it without a separate action.
                                "workspaceEdit": {"documentChanges": True},
                            },
                            "textDocument": {
                                "definition": {"linkSupport": True},
                                "declaration": {"linkSupport": True},
                                "typeDefinition": {"linkSupport": True},
                                "references": {},
                                "hover": {"contentFormat": ["markdown", "plaintext"]},
                                "completion": {
                                    "dynamicRegistration": False,
                                    "completionItem": {
                                        "snippetSupport": False,
                                        "documentationFormat": ["plaintext"],
                                    },
                                },
                                "signatureHelp": {
                                    "dynamicRegistration": False,
                                    "signatureInformation": {
                                        "documentationFormat": ["plaintext"],
                                        "parameterInformation": {
                                            "labelOffsetSupport": True
                                        },
                                    },
                                },
                                "rename": {
                                    "dynamicRegistration": False,
                                    "prepareSupport": True,
                                },
                                "documentHighlight": {
                                    "dynamicRegistration": False,
                                },
                                "codeAction": {
                                    "dynamicRegistration": False,
                                },
                                "documentSymbol": {
                                    "hierarchicalDocumentSymbolSupport": True
                                },
                                "publishDiagnostics": {"relatedInformation": True},
                            },
                        },
                    }
                    init = await asyncio.wait_for(
                        self.server.send.initialize(params),
                        timeout=settings.initialize_timeout_s,
                    )
                    caps = init.get("capabilities") if isinstance(init, dict) else None
                    if not isinstance(caps, dict):
                        raise TypeError("invalid_pyright_capabilities")
                    if caps.get("positionEncoding", "utf-16") != "utf-16":
                        raise ValueError("unsupported_pyright_position_encoding")
                    self.capabilities = dict(caps)
                    self.server.notify.initialized({})
                    self.server.notify.workspace_did_change_configuration(
                        {
                            "settings": {
                                "python": {
                                    "analysis": {
                                        "typeCheckingMode": settings.type_checking_mode,
                                        "diagnosticMode": settings.diagnostic_mode,
                                    }
                                },
                                "pyright": {"disableLanguageServices": False},
                            }
                        }
                    )
                    initialized = True
                    yield self
                finally:
                    try:
                        if initialized:
                            await asyncio.wait_for(
                                self.server.shutdown(),
                                timeout=settings.shutdown_timeout_s,
                            )
                    finally:
                        await asyncio.wait_for(
                            self.server.stop(), timeout=settings.shutdown_timeout_s + 15
                        )

        async def request_definition(
            self, relative_file_path: str, line: int, column: int
        ) -> list[dict]:
            safe, path = _authorized_file(root, relative_file_path)
            with self.open_file(safe):
                raw = await self.server.send.definition(
                    {
                        "textDocument": {"uri": path.as_uri()},
                        "position": {"line": line, "character": column},
                    }
                )
            return normalize_locations(root, raw)

        async def request_references(
            self, relative_file_path: str, line: int, column: int
        ) -> list[dict]:
            safe, path = _authorized_file(root, relative_file_path)
            with self.open_file(safe):
                raw = await self.server.send.references(
                    {
                        "textDocument": {"uri": path.as_uri()},
                        "position": {"line": line, "character": column},
                        "context": {"includeDeclaration": False},
                    }
                )
            return normalize_locations(root, raw)

        async def next_diagnostics(self, *, timeout_s: float = 5.0) -> dict:
            return await asyncio.wait_for(self.diagnostics.get(), timeout=timeout_s)

    return PyrightAdapter()
