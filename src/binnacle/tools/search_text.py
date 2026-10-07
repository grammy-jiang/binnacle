"""Compatibility alias for the relocated Search MCP adapter during G6."""

import sys as _sys

from binnacle.features.search.tools import search_text as _implementation
from binnacle.features.search.tools.search_text import register, search_text_impl

__all__ = ["register", "search_text_impl"]

_sys.modules[__name__] = _implementation
