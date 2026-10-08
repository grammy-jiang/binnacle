"""Compatibility identity alias for diagnostics-owned doctor aggregate."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.diagnostics import doctor as _typed_impl
    from binnacle.diagnostics.doctor import *

    Check = _typed_impl.Check
    Deployment = _typed_impl.Deployment
    run_all = _typed_impl.run_all
else:
    import sys

    from binnacle.diagnostics import doctor as _impl

    sys.modules[__name__] = _impl
