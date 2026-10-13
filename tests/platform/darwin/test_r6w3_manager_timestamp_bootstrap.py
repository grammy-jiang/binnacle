"""R6W3 merge P2: early manager bootstrap must keep timestamped log windows.

Fresh child has an unused root logger. No service is created; pinned manager
import is replaced by a logging-only stub that exercises the real formatting
call and then the normal operational telemetry configuration.
"""

from __future__ import annotations

import re
import subprocess
import sys

import pytest

from binnacle.platform.darwin.daemon_logstats import _stamp


@pytest.mark.parametrize("system", ["Linux", "Darwin"])
def test_manager_early_bootstrap_keeps_timestamped_exit_log(system):
    source = """
import logging, sys
from binnacle import manager_bootstrap as boot
from binnacle import startup_imports
from binnacle.platform.darwin import job_manager_telemetry as telemetry

def configured(**kwargs):
    logging.basicConfig(level=logging.INFO, format=kwargs["log_format"],
                        datefmt="%Y-%m-%dT%H:%M:%S")

boot.capture_startup_root = lambda **_kwargs: None
boot.import_manager_modules = configured
boot.bootstrap_manager_entry(sys.argv[1])
telemetry.configure_job_manager_logging()
logging.getLogger("binnacle.job_manager").info(
    "event=job_exit job_id=synthetic owner=manager"
)
"""
    proc = subprocess.run(
        [sys.executable, "-c", source, system],
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-500:]
    lines = [line for line in proc.stderr.splitlines() if "event=job_exit" in line]
    assert len(lines) == 1
    assert re.match(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3} INFO: event=job_exit ",
        lines[0],
    ), lines
    assert _stamp(lines[0]) is not None
