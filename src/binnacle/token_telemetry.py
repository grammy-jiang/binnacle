"""Compatibility alias for observability-owned token_telemetry."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.observability.token_telemetry import *
    from binnacle.observability.token_telemetry import (
        _load_encoding as _load_encoding,  # noqa: PLC0414
    )
else:
    import sys

    from binnacle.observability import token_telemetry as _impl

    sys.modules[__name__] = _impl
