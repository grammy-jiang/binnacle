"""Compatibility alias for observability-owned logstats."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.observability.logstats import *
    from binnacle.observability.logstats import (
        _appended_fields as _appended_fields,  # noqa: PLC0414
    )
    from binnacle.observability.logstats import (
        _area as _area,  # noqa: PLC0414
    )
    from binnacle.observability.logstats import (
        _first_word as _first_word,  # noqa: PLC0414
    )
    from binnacle.observability.logstats import (
        _int as _int,  # noqa: PLC0414
    )
    from binnacle.observability.logstats import (
        _json_args as _json_args,  # noqa: PLC0414
    )
    from binnacle.observability.logstats import (
        _path_hash as _path_hash,  # noqa: PLC0414
    )
    from binnacle.observability.logstats import (
        _request_key as _request_key,  # noqa: PLC0414
    )
    from binnacle.observability.logstats import (
        analyze_adaptive_discovery as analyze_adaptive_discovery,  # noqa: PLC0414
    )
else:
    import sys

    from binnacle.observability import logstats as _impl

    sys.modules[__name__] = _impl
