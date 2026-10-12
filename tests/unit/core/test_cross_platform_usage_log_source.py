"""Only the composition layer chooses the concrete native usage-log source."""

from __future__ import annotations

from binnacle.platform import composition


def test_darwin_production_log_reader_selected_at_composition(monkeypatch):
    from binnacle.platform.darwin.daemon_logstats import DarwinDaemonLogStatsSource

    monkeypatch.setattr(composition, "host_os_family", lambda: "darwin")
    seen = []

    def read(self, units, since, until=None):
        seen.append((units, since, until))
        return "DARWIN"

    monkeypatch.setattr(DarwinDaemonLogStatsSource, "read_spec", read)
    assert (
        composition.read_usage_service_logs(
            ("binnacle-mcp", "binnacle-jobs"), "-2 days", "now"
        )
        == "DARWIN"
    )
    assert seen == [(("binnacle-mcp", "binnacle-jobs"), "-2 days", "now")]


def test_linux_still_uses_original_journal_query(monkeypatch):
    from binnacle.platform.linux.service_journal import JournalServiceLogSource

    monkeypatch.setattr(composition, "host_os_family", lambda: "linux")
    seen = []

    def read(self, units, since, until=None):
        seen.append((units, since, until))
        return "LINUX"

    monkeypatch.setattr(JournalServiceLogSource, "read_spec", read)
    assert (
        composition.read_usage_service_logs(
            ("binnacle-mcp", "binnacle-jobs"), "-1 hour"
        )
        == "LINUX"
    )
    assert seen == [(("binnacle-mcp", "binnacle-jobs"), "-1 hour", None)]
