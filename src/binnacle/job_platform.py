"""Explicit Linux defaults selected only by job-engine/manager composition."""

from binnacle.process_contracts import ProcessBackend
from binnacle.resource_contracts import ResourceAccounting


def create_process_backend() -> ProcessBackend:
    from binnacle.job_process import LinuxProcessBackend

    return LinuxProcessBackend()


def create_resource_accounting() -> ResourceAccounting:
    from binnacle.job_cgroup import CgroupResourceAccounting

    return CgroupResourceAccounting()
