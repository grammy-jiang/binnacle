"""OI-10: journal acquisition is lazy and the analytics core is Linux-free."""

import os
import subprocess
import sys
from pathlib import Path


def test_pure_log_analytics_imports_without_linux_and_parses(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("BINNACLE_")}
    env["BINNACLE_CONFIG_FILE"] = str(tmp_path / "no-config.toml")
    script = """
import importlib.abc, sys
class BlockLinux(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("binnacle.platform.linux","binnacle.observability.linux")):
            raise ImportError("blocked: " + fullname)
sys.meta_path.insert(0, BlockLinux())
from binnacle.observability import logstats
from binnacle.observability import logstats_io
from binnacle.observability import logstats_parse
records, startups = logstats.parse("INFO: event=job_start job_id=abc\\n")
result = logstats.analyze(records, startups)
assert hasattr(result, "job_exits")
assert not any(name.startswith("binnacle.platform.linux") for name in sys.modules)
try:
    logstats.fetch_journal("unit", "-1s")
except ImportError as e:
    assert "blocked:" in str(e)
else:
    raise AssertionError("explicit Linux journal read must fail with adapter blocked")
print("PURE_LOG_PASS")
"""
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
    assert "PURE_LOG_PASS" in proc.stdout
