"""Compatibility module alias for Linux-owned unit-definition diagnostics.

Retain the public `binnacle.service_unit_linux` import path while the
implementation resides at `binnacle.platform.linux.service_unit_linux`.
Both imports intentionally return the same module so monkeypatches work.
"""

import sys

from binnacle.platform.linux import service_unit_linux as _impl

sys.modules[__name__] = _impl
