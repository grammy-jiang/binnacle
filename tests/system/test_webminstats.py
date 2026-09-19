from __future__ import annotations

from pathlib import Path

from binnacle import cli, logstats, webminstats


def write_metric(root: Path, name: str, values: list[tuple[int, float]]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_text("".join(f"{ts} {value}\n" for ts, value in values))


def test_webmin_history_window_and_render(tmp_path: Path, monkeypatch):
    root = tmp_path / "history"
    timestamps = [1_000, 1_300, 1_600, 1_900]
    values: dict[str, list[int | float]] = {
        "cpuidle": [90, 80, 25, 0],
        "cpuio": [0, 1, 2, 3],
        "load": [0.2, 0.5, 3.5, 5.0],
        "load5": [0.2, 0.4, 2.0, 3.0],
        "load15": [0.1, 0.3, 1.0, 2.0],
        "memused": [4, 5, 6, 7],
        "swapused": [0, 0, 1, 2],
        "procs": [200, 210, 220, 230],
        "drivetemp": [35, 36, 45, 50],
    }
    for name, series in values.items():
        scale = 1024**3 if name in {"memused", "swapused"} else 1
        write_metric(root, name, list(zip(timestamps, [x * scale for x in series])))
    for name in set(webminstats.METRICS) - set(values):
        write_metric(root, name, [])

    monkeypatch.setattr(webminstats, "HISTORY_DIR", root)
    monkeypatch.setattr(
        webminstats,
        "_resolve_time",
        lambda spec, default_now=False: 1_300 if spec == "start" else 1_900,
    )
    stats = webminstats.load("start", "end")

    assert stats.samples == 3
    assert stats.interval_s == 300
    assert [p.value for p in stats.series["cpuidle"]] == [80, 25, 0]
    text = webminstats.render(stats)
    assert "system resources (Webmin system-status)" in text
    assert "interval≈300s" in text
    assert "CPU busy" in text and "100.0%" in text
    assert "memory used" in text and "7.0 GiB" in text
    assert "peak timestamps:" in text


def test_stats_does_not_read_webmin_by_default(monkeypatch, capsys):
    monkeypatch.setattr(logstats, "fetch_journal", lambda *args: "")
    monkeypatch.setattr(
        webminstats,
        "load",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Webmin read")),
    )
    cli.stats(since="-24 hours", system_resources=False)
    assert "requests: 0" in capsys.readouterr().out


def test_stats_system_resources_uses_same_window(monkeypatch, capsys):
    monkeypatch.setattr(logstats, "fetch_journal", lambda *args: "")
    seen = []
    monkeypatch.setattr(
        webminstats,
        "load",
        lambda since, until: seen.append((since, until)) or object(),
    )
    monkeypatch.setattr(webminstats, "render", lambda value: "WEBMIN-RESOURCE-REPORT")

    cli.stats(
        since="2026-09-18 10:00:00",
        until="2026-09-19 10:00:00",
        system_resources=True,
    )
    out = capsys.readouterr().out
    assert seen == [("2026-09-18 10:00:00", "2026-09-19 10:00:00")]
    assert "WEBMIN-RESOURCE-REPORT" in out


def test_batch_reader_uses_one_sudo_on_permission_error(tmp_path: Path, monkeypatch):
    root = tmp_path / "history"
    root.mkdir()
    for name in webminstats.METRICS:
        (root / name).write_text("1000 1\n")
    monkeypatch.setattr(webminstats, "HISTORY_DIR", root)

    real_read_text = Path.read_text

    def denied(self: Path, *args, **kwargs):
        if self.parent == root:
            raise PermissionError(self)
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", denied)
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        payload = {name: "1000 1\n" for name in webminstats.METRICS}
        return __import__("subprocess").CompletedProcess(
            args, 0, __import__("json").dumps(payload), ""
        )

    monkeypatch.setattr(webminstats.subprocess, "run", fake_run)
    texts = webminstats._read_all_metric_texts()
    assert len(calls) == 1
    assert calls[0][:4] == ["sudo", "-n", "python3", "-c"]
    assert set(texts) == set(webminstats.METRICS)
    assert all(text == "1000 1\n" for text in texts.values())


def test_batch_reader_reports_sudo_and_payload_failures(tmp_path: Path, monkeypatch):
    root = tmp_path / "history"
    root.mkdir()
    for name in webminstats.METRICS:
        (root / name).write_text("1000 1\n")
    monkeypatch.setattr(webminstats, "HISTORY_DIR", root)

    monkeypatch.setattr(
        Path,
        "read_text",
        lambda self, *a, **k: (_ for _ in ()).throw(PermissionError(self)),
    )
    cp = __import__("subprocess").CompletedProcess

    monkeypatch.setattr(
        webminstats.subprocess, "run", lambda args, **kw: cp(args, 1, "", "denied")
    )
    try:
        webminstats._read_all_metric_texts()
    except RuntimeError as exc:
        assert "not readable" in str(exc)
    else:
        raise AssertionError("sudo failure should be reported")

    monkeypatch.setattr(
        webminstats.subprocess, "run", lambda args, **kw: cp(args, 0, "not-json", "")
    )
    try:
        webminstats._read_all_metric_texts()
    except RuntimeError as exc:
        assert "invalid JSON" in str(exc)
    else:
        raise AssertionError("invalid JSON should be rejected")

    monkeypatch.setattr(
        webminstats.subprocess, "run", lambda args, **kw: cp(args, 0, "[]", "")
    )
    try:
        webminstats._read_all_metric_texts()
    except TypeError as exc:
        assert "invalid payload" in str(exc)
    else:
        raise AssertionError("non-object payload should be rejected")


def test_time_validation_and_empty_window(monkeypatch):
    monkeypatch.setattr(
        webminstats,
        "_read_all_metric_texts",
        lambda: {name: "" for name in webminstats.METRICS},
    )
    monkeypatch.setattr(
        webminstats,
        "_resolve_time",
        lambda spec, default_now=False: 2_000 if spec == "late" else 1_000,
    )
    try:
        webminstats.load("late", "early")
    except ValueError as exc:
        assert "until" in str(exc)
    else:
        raise AssertionError("reverse window should fail")

    monkeypatch.setattr(
        webminstats, "_resolve_time", lambda spec, default_now=False: 1_000
    )
    stats = webminstats.load("start", "end")
    assert stats.samples == 0
    assert stats.interval_s == 0
    assert "no Webmin samples" in webminstats.render(stats)


def test_time_parser_and_malformed_metric_lines(monkeypatch):
    cp = __import__("subprocess").CompletedProcess
    monkeypatch.setattr(
        webminstats.subprocess,
        "run",
        lambda args, **kw: cp(args, 0, "1234\n", ""),
    )
    assert webminstats._resolve_time("yesterday") == 1234

    monkeypatch.setattr(
        webminstats.subprocess,
        "run",
        lambda args, **kw: cp(args, 1, "", "bad date"),
    )
    try:
        webminstats._resolve_time("nonsense")
    except ValueError as exc:
        assert "Cannot parse" in str(exc)
    else:
        raise AssertionError("invalid date should fail")

    points = webminstats._parse_metric_text("1000 1.5\nmissing\nnope two\n1300 2\n")
    assert [(p.ts, p.value) for p in points] == [(1000, 1.5), (1300, 2.0)]
