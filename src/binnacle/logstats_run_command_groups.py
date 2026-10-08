"""Compatibility alias for observability-owned logstats_run_command_groups."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.observability.logstats_run_command_groups import *
else:
    import sys

    from binnacle.observability import logstats_run_command_groups as _impl

    sys.modules[__name__] = _impl
