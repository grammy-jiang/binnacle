"""Compatibility alias for the Linux observability Webmin history reader."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.observability.linux.webminstats import *
else:
    import sys

    from binnacle.observability.linux import webminstats as _impl

    sys.modules[__name__] = _impl
