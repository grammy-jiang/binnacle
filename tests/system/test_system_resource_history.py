"""CLI resource-history opt-in, lazy construction, and adapter parity."""

import pytest

from binnacle import cli, logstats


def test_cli_constructs_resource_provider_only_for_opt_in(monkeypatch, capsys):
    from binnacle import system_resource_history

    calls = []

    class History:
        def render_window(self, since, until):
            calls.append((since, until))
            return "RESOURCES"

    def create():
        calls.append("create")
        return History()

    monkeypatch.setattr(
        system_resource_history, "create_system_resource_history", create
    )
    monkeypatch.setattr(logstats, "fetch_journal", lambda *a: "")
    monkeypatch.setattr(logstats, "parse", lambda raw: ([], []))
    monkeypatch.setattr(logstats, "analyze", lambda *a: None)
    monkeypatch.setattr(logstats, "render", lambda _: "USAGE")
    cli.stats(since="-1 hour", until="now", system_resources=False)
    assert calls == []
    assert "RESOURCES" not in capsys.readouterr().out
    cli.stats(since="-1 hour", until="now", system_resources=True)
    assert calls == ["create", ("-1 hour", "now")]
    assert capsys.readouterr().out.endswith("USAGE\n\nRESOURCES\n")


def test_webmin_adapter_preserves_errors_and_window(monkeypatch):
    from binnacle import system_resource_history, webminstats

    def no_read(*args):
        pytest.fail("provider construction read history")

    monkeypatch.setattr(webminstats, "load", no_read)
    history = system_resource_history.create_system_resource_history()
    error = PermissionError("history inaccessible")

    def denied(since, until):
        assert (since, until) == ("-2 hours", None)
        raise error

    monkeypatch.setattr(webminstats, "load", denied)
    with pytest.raises(PermissionError) as exc:
        history.render_window("-2 hours", None)
    assert exc.value is error
