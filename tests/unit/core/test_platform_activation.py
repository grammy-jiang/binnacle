"""Explicit platform construction and job-engine activation contracts."""


def test_constructors_are_lazy_and_return_current_adapters(monkeypatch):
    from binnacle import job_cgroup, job_platform, job_process

    process = object()
    accounting = object()
    monkeypatch.setattr(job_process, "LinuxProcessBackend", lambda: process)
    monkeypatch.setattr(job_cgroup, "CgroupResourceAccounting", lambda: accounting)
    assert job_platform.create_process_backend() is process
    assert job_platform.create_resource_accounting() is accounting
