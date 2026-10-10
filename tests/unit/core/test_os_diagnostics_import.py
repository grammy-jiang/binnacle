"""OS5: generic diagnostics/observability import without Linux adapters."""

import os
import subprocess
import sys
from pathlib import Path


def test_doctor_core_and_render_are_linux_import_independent(tmp_path):
    script = """
import importlib.abc, sys
class NoLinux(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("binnacle.platform.linux",
                                "binnacle.observability.linux",
                                "binnacle.deployment.linux")):
            raise ImportError("blocked adapter: " + fullname)
sys.meta_path.insert(0, NoLinux())
from binnacle.diagnostics import doctor, doctor_jobs, doctor_render, doctor_common
from binnacle.doctor_contracts import Check, fail, warn, ok
from binnacle.observability import logstats
assert callable(doctor.run_all)
assert callable(doctor_jobs.server_busy_reasons)
assert callable(doctor_render.render)
data = [ok("core", "good"), warn("core", "uncertain")]
text, code = doctor_render.render(data)
assert code == 0 and "good" in text
records, startup = logstats.parse("INFO: event=job_exit job_id=abcdef\\n")
assert hasattr(logstats.analyze(records, startup), "job_exits")
print("OS5_DOCTOR_PURE_IMPORT_PASS")
"""
    env = {k: v for k, v in os.environ.items() if not k.startswith("BINNACLE_")}
    env["BINNACLE_CONFIG_FILE"] = str(tmp_path / "absent.toml")
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[3],
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "OS5_DOCTOR_PURE_IMPORT_PASS" in proc.stdout
