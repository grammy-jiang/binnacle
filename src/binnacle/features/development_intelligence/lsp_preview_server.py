"""P2.7 QA-only FastMCP child for private Development Intelligence trials.

No public semantic-tool release is authorized here: application composition
requires a separate, deliberately non-configurable test/review gate. The normal
server factory never passes that gate. This child uses Binnacle P2.6 for
admission/lifetimes, P2.5 for files and native multilspy for every LSP frame.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import anyio
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from binnacle.config import RootsSettings
from binnacle.config_development_intelligence import DevelopmentIntelligenceSettings

from .lsp_provider_manager import PrivateProviderManager

_CLEANUP_CEILING_SECONDS = 90.0

PREVIEW_NAME = "lsp_definition_preview_private"


class _PreviewLifespan:
    """Per-child context: never reuse a P2.6 manager across active lifespans."""

    def __init__(self) -> None:
        self.active: Any | None = None
        self.starts = 0
        self.closed = 0
        self.last_close: Any | None = None
        self.poisoned = False

    def _observe_cleanup(self, closing: asyncio.Task[Any]) -> None:
        """Consume late task errors; only verified cleanup clears ownership."""
        try:
            evidence = closing.result()
        except BaseException:  # noqa: BLE001 - even cancellation poisons ownership
            self.poisoned = True
            return
        self.last_close = evidence
        if evidence.cleanup_unverified:
            self.poisoned = True
        elif not self.poisoned:
            self.active = None
            self.closed += 1


def validate_private_profile(settings: DevelopmentIntelligenceSettings) -> bool:
    """Return false for disabled discovery; reject misconfigured opt-in.

    This is *not* an OS confinement certificate or a P5 tool-release decision.
    """
    if not settings.enabled or not settings.discovery_enabled:
        return False
    profile = settings.profiles.get("pyright")
    if profile is None or not profile.enabled:
        return False
    if (
        profile.mode != "explicit_trust_only"
        or profile.source != "trusted_absolute"
        or not profile.executable
        or profile.argv
        or profile.env
    ):
        raise ValueError("private_pyright_preview_requires_trusted_profile")
    # The native P2.4 owner checks the executable on first launch. Merely
    # discovering an enabled tool must not eagerly spawn or read a workspace.
    return True


def create_private_lsp_preview_server(
    *,
    feature_settings: DevelopmentIntelligenceSettings,
    roots: RootsSettings,
    manager_factory: Callable[..., Any] = PrivateProviderManager,
) -> FastMCP:
    """Create one FastMCP child; its P2.6 manager is created by lifespan only.

    The parent owns the decision to mount this child. This constructor cannot
    override the production P5 gate and must never run at package import.
    """
    if not validate_private_profile(feature_settings):
        raise ValueError("private_lsp_preview_not_enabled")
    settings = feature_settings.model_copy(deep=True)
    roots = roots.model_copy(deep=True)
    _ = roots.canonical_allowed
    lifetime = _PreviewLifespan()

    @asynccontextmanager
    async def lifespan(_server):
        if lifetime.active is not None or lifetime.poisoned:
            raise RuntimeError("private_lsp_lifespan_overlap")
        manager = manager_factory(settings, roots)
        lifetime.active = manager
        lifetime.starts += 1
        try:
            async with manager:
                yield {}
        finally:
            # FastMCP session cancellation must not cancel the P2.4 cleanup.
            # An unverified/unfinished cleanup poisons this root generation;
            # never silently allow a second resident Manager over leaked PIDs.
            closing = asyncio.create_task(manager.aclose())
            closing.add_done_callback(lifetime._observe_cleanup)
            cleanup_seconds = min(
                _CLEANUP_CEILING_SECONDS, max(5.0, settings.request_timeout_s * 2)
            )
            try:
                # FastMCP runs under AnyIO: cancellation scopes must be
                # shielded at the framework level, not only with asyncio.
                with anyio.CancelScope(shield=True):
                    evidence = await asyncio.wait_for(
                        asyncio.shield(closing), timeout=cleanup_seconds
                    )
            except asyncio.CancelledError:
                # A direct asyncio cancellation may escape the AnyIO scope.
                # The shielded close task and done callback still clean up.
                raise
            except Exception as exc:
                lifetime.poisoned = True
                raise RuntimeError("private_lsp_preview_cleanup_unverified") from exc
            if evidence.cleanup_unverified:
                lifetime.poisoned = True
                raise RuntimeError("private_lsp_preview_cleanup_unverified")

    child = FastMCP(
        "binnacle-private-lsp-preview",
        lifespan=lifespan,
        on_duplicate="error",
        mask_error_details=True,
        instructions=(
            "Private Development Intelligence review tool; not a released "
            "inspect_symbol contract. Only operator-trusted Pyright profiles."
        ),
    )

    @child.tool(
        name=PREVIEW_NAME,
        description=(
            "PRIVATE TEST-ONLY Pyright definition preview. Input is an absolute "
            "source file already authorized by Binnacle operator roots; line "
            "and column are 1-based Unicode codepoint positions. "
            "expected_symbol must match the exact identifier under the cursor. "
            "Responses are bounded workspace-relative locations. This preview "
            "is not an OS sandbox or a production inspect_symbol release."
        ),
        # No readOnlyHint: Pyright can write type stubs via server-side commands.
        # P3 OS confinement and P5 tool-release review are still outstanding.
    )
    async def definition_preview(
        source_file: str,
        line: int,
        column: int,
        expected_symbol: str,
    ) -> dict[str, Any]:
        manager = lifetime.active
        if manager is None or manager.closed:
            raise ToolError("private_lsp_preview_lifecycle_unavailable")
        try:
            # source_file is interpreted by P2.5 only; this child does not
            # resolve, authorize or open files on behalf of the caller.
            raw = await manager.definition(
                Path(source_file),
                line=line,
                column=column,
                expected_symbol=expected_symbol,
            )
            # P2.5 verifies URI scope and ranges. Always discard the absolute
            # host path/URI before constructing the MCP-facing preview result.
            result = [
                {"relative_path": item["relativePath"], "range": item["range"]}
                for item in raw
            ]
            return {"status": "ok" if result else "not_found", "locations": result}
        except asyncio.CancelledError:
            raise
        except ValueError:
            # Never forward strings from source, filesystem or provider errors.
            raise ToolError("private_lsp_invalid_source_or_anchor") from None
        except Exception:  # noqa: BLE001 - catch ALL downstream redaction cases
            raise ToolError("private_lsp_provider_unavailable") from None

    # Introspection is explicitly private and only used by native QA tests.
    child._private_preview_lifespan = lifetime  # type: ignore[attr-defined]
    return child
