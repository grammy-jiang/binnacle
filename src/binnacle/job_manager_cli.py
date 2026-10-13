"""Production Linux job-manager console entry with a guarded import boundary.

The normal service invokes the binnacle-jobs executable, not python -m.
Do not import job_manager here until required imports have been validated.
"""

from __future__ import annotations


def main() -> None:
    """Fail with typed startup evidence before loading the job-manager backend."""
    from binnacle.manager_bootstrap import bootstrap_manager_entry

    bootstrap_manager_entry("Linux")

    from binnacle.features.commands.job_manager import main as start

    start()
