"""Compatibility module alias to the G5-stable neutral Check contract."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.doctor_contracts import *
else:
    import sys

    from binnacle import doctor_contracts as _impl

    sys.modules[__name__] = _impl
