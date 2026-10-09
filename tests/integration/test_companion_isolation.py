"""Core construction must not need reliability, tunnel, or Webmin imports."""

import subprocess
import sys

from tests.integration.test_packaging_smoke import clean_env


def test_core_server_and_doctor_without_companion_implementations(tmp_path):
    token = tmp_path / "token"
    token.write_text("Bearer isolated-token\n")
    config = tmp_path / "config.toml"
    config.write_text(
        f'[auth]\ntoken_file = "{token}"\n[jobs]\ndir = "{tmp_path / "jobs"}"\nowner = "embedded"\n'
    )
    script = """
import asyncio, importlib.abc, sys
class NoCompanions(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('binnacle.companions', 'binnacle.observability.linux.webminstats')):
            raise AssertionError('core tried to import companion: ' + fullname)
sys.meta_path.insert(0, NoCompanions())
from binnacle import cli, server
from binnacle.diagnostics import doctor
from fastmcp import Client
root = server.create_server()
assert not hasattr(doctor, 'check_uplink')
async def check():
    async with Client(root, cache=False) as client:
        assert [t.name for t in await client.list_tools()] == ['read_file', 'list_files', 'search_text', 'edit_file', 'write_file', 'run_command', 'job_status', 'stop_job']
asyncio.run(check())
print('isolated-core-ok')
"""
    proc = subprocess.run(
        [sys.executable, "-c", script],
        env=clean_env(config),
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "isolated-core-ok"
