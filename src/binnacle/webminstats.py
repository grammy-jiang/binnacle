"""Compatibility alias for the Linux observability Webmin history reader."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.observability.linux import webminstats as _typed_impl
    from binnacle.observability.linux.webminstats import *

    _read_all_metric_texts = _typed_impl._read_all_metric_texts
else:
    import sys

    from binnacle.observability.linux import webminstats as _impl

    sys.modules[__name__] = _impl
