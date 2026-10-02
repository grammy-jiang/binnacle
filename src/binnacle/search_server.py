"""Focused Search server using the existing MCP adapter."""

from fastmcp import FastMCP

from binnacle.tools import search_text


def create_search_server() -> FastMCP:
    """Build an independent Search child for native FastMCP composition."""
    search = FastMCP("binnacle-search", on_duplicate="error")
    search_text.register(search)
    return search
