"""Compatibility alias for Commands-owned jobs."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.features.commands.jobs import *
    from binnacle.features.commands.jobs import (
        _PROCESS_BACKEND as _PROCESS_BACKEND,  # noqa: PLC0414
    )
    from binnacle.features.commands.jobs import (
        _RESOURCE_ACCOUNTING as _RESOURCE_ACCOUNTING,  # noqa: PLC0414
    )
    from binnacle.features.commands.jobs import (
        _STORE_LOCK as _STORE_LOCK,  # noqa: PLC0414
    )
    from binnacle.features.commands.jobs import (
        _job_dir as _job_dir,  # noqa: PLC0414
    )
    from binnacle.features.commands.jobs import (
        _prune as _prune,  # noqa: PLC0414
    )
    from binnacle.features.commands.jobs import (
        _read_meta as _read_meta,  # noqa: PLC0414
    )
    from binnacle.features.commands.jobs import (
        _remove_job_dir as _remove_job_dir,  # noqa: PLC0414
    )
    from binnacle.features.commands.jobs import (
        _resolve_owner_mode as _resolve_owner_mode,  # noqa: PLC0414
    )
    from binnacle.features.commands.jobs import (
        _save_final_resource_meta as _save_final_resource_meta,  # noqa: PLC0414
    )
    from binnacle.features.commands.jobs import (
        _write_meta as _write_meta,  # noqa: PLC0414
    )
else:
    import sys

    from binnacle.features.commands import jobs as _impl

    sys.modules[__name__] = _impl
