"""P2.7 explicitly gated, conditional FastMCP child composition.

This helper is imported ONLY when code-driven private QA gate is enabled.
User configuration alone cannot pass the P4/P5 semantic-tool release gate.
"""

from __future__ import annotations

from collections.abc import Callable

from fastmcp import FastMCP

from binnacle.config import RootsSettings
from binnacle.config_development_intelligence import DevelopmentIntelligenceSettings


def mount_private_preview(
    parent: FastMCP,
    *,
    feature_settings: DevelopmentIntelligenceSettings,
    roots: RootsSettings,
    child_factory: Callable[..., FastMCP] | None = None,
) -> bool:
    """Mount only with explicit discovery, provider trust and code-only gate.

    Returns whether the child actually mounted; a disabled profile stays
    entirely absent from list, discover and direct MCP tool lookup.
    """
    if not feature_settings.enabled or not feature_settings.discovery_enabled:
        return False

    from .lsp_preview_server import (
        create_private_lsp_preview_server,
        validate_private_profile,
    )

    if not validate_private_profile(feature_settings):
        return False
    factory = child_factory or create_private_lsp_preview_server
    parent.mount(factory(feature_settings=feature_settings, roots=roots))
    return True
