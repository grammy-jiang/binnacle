"""The stable owner survives independently constructed, short-lived MCP workers."""

from pathlib import Path

from tests.integration.job_reload_support import reload_scenario


def test_separate_workers_share_manager_cursor_and_idempotent_stop(tmp_path):
    source = Path(__file__).resolve().parents[2] / "src"
    reload_scenario(tmp_path, source, source)
