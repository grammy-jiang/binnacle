"""Shared opt-in fixtures for integration tests."""

import shutil
import tempfile
from pathlib import Path

import pytest

from tests.integration._jobs_socket_fixture import ensure_test_jobs_socket

# Must run before anything composes settings (test modules import the jobs
# module at collection); a no-op on Linux and when the env var is set.
ensure_test_jobs_socket()

from binnacle.features.commands import jobs as jobstore


@pytest.fixture()
def _short_job_warmup(monkeypatch):
    """Use a short warm-up only in integration modules that opt in."""
    monkeypatch.setattr(jobstore, "WARMUP_S", 0.05)


@pytest.fixture
def run_policy(monkeypatch):
    """Build the real root with an explicitly configured Commands child."""
    from binnacle import server

    factory = server.create_commands_server

    def configure(settings):
        def commands(**kwargs):
            return factory(**{**kwargs, "run_settings": settings})

        monkeypatch.setattr(server, "create_commands_server", commands)
        monkeypatch.setattr(server, "mcp", server.create_server())

    return configure


@pytest.fixture
def tmp_path_is_allowed_root(tmp_path, monkeypatch):
    """Opt in: native temp roots (macOS /private/var/folders) sit outside the
    default roots, so grant this test's own temp directory explicitly."""
    from binnacle.config import get_settings

    roots = get_settings().roots
    monkeypatch.setattr(roots, "extra_roots", (*roots.extra_roots, tmp_path.resolve()))


@pytest.fixture
def default_root_tmp_path():
    """Opt in: a temp directory under the default /tmp root, for tests whose
    server is built at import and so cannot be granted a per-test root."""
    path = Path(tempfile.mkdtemp(prefix="binnacle-it-", dir="/tmp")).resolve()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
