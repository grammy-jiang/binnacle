from __future__ import annotations

from scripts import resource_monitor as rm


def test_trigger_expression_uses_kernel_psi_units():
    spec = rm.Trigger("cpu", "/proc/pressure/cpu", "some", 2_500_000, 8, 1800)
    assert spec.expression == "some 2500000 10000000"


def test_daily_count_is_per_resource_and_only_counts_today(tmp_path, monkeypatch):
    monkeypatch.setattr(rm, "BURST_ROOT", tmp_path)
    now = 1_790_660_000.0
    prefix = rm.datetime.fromtimestamp(now).astimezone().strftime("%Y%m%d")
    (tmp_path / f"{prefix}T120000+1000-psi-cpu").mkdir()
    (tmp_path / f"{prefix}T120100+1000-psi-io").mkdir()
    (tmp_path / f"{prefix}T120200+1000-manual").mkdir()
    (tmp_path / "19990101T000000+0000-psi-cpu").mkdir()
    assert rm._daily_count(now, "cpu") == 1
    assert rm._daily_count(now, "io") == 1
    assert rm._daily_count(now, "memory") == 0


def test_monitor_blocks_in_poll_without_periodic_timeout(monkeypatch):
    monitor = rm.Monitor(burst_seconds=2)
    calls: list[object] = []

    class Stop(Exception):
        pass

    class Poller:
        def poll(self, *args):
            calls.append(args)
            raise Stop

    monitor.poller = Poller()
    monkeypatch.setattr(monitor, "open_triggers", lambda: None)
    monkeypatch.setattr(monitor, "close", lambda: None)
    try:
        monitor.run()
    except Stop:
        pass
    assert calls == [()]


def test_monitor_module_has_no_reconciliation_interval():
    assert not hasattr(rm, "RECONCILE_S")
    assert not hasattr(rm, "reconcile_jobs")


def test_default_quotas_and_intervals_are_resource_specific():
    specs = {spec.name: spec for spec in rm.TRIGGERS}
    assert (specs["cpu"].max_bursts_per_day, specs["cpu"].min_interval_s) == (8, 1800)
    assert (specs["io"].max_bursts_per_day, specs["io"].min_interval_s) == (6, 2700)
    assert (specs["memory"].max_bursts_per_day, specs["memory"].min_interval_s) == (
        4,
        1800,
    )


def test_monitor_restores_per_resource_timestamps_with_legacy_fallback(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(rm, "STATE_ROOT", tmp_path)
    (tmp_path / "last-burst").write_text("100")
    (tmp_path / "last-burst-cpu").write_text("200")
    monitor = rm.Monitor(burst_seconds=2)
    assert monitor.last_burst["cpu"] == 200
    assert monitor.last_burst["io"] == 100
    assert monitor.last_burst["memory"] == 100


def test_daily_cap_for_one_resource_does_not_consume_another(tmp_path, monkeypatch):
    monkeypatch.setattr(rm, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(rm, "BURST_ROOT", tmp_path / "bursts")
    monkeypatch.setattr(rm.time, "time", lambda: 10_000.0)
    monitor = rm.Monitor(burst_seconds=2)
    monitor.last_burst = {"cpu": 0.0, "io": 0.0, "memory": 0.0}
    started: list[str] = []
    monkeypatch.setattr(
        rm, "run_burst", lambda trigger, seconds: started.append(trigger)
    )
    monkeypatch.setattr(
        rm, "_daily_count", lambda now, resource: 8 if resource == "cpu" else 0
    )

    class ImmediateThread:
        def __init__(self, *, target, name, daemon):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(rm.threading, "Thread", ImmediateThread)
    specs = {spec.name: spec for spec in rm.TRIGGERS}
    monitor._start_burst(specs["cpu"])
    monitor._start_burst(specs["io"])
    assert started == ["psi-io"]
    assert (rm.STATE_ROOT / "last-burst-io").read_text() == "10000.0"
    assert (rm.STATE_ROOT / "last-burst").read_text() == "10000.0"


def test_min_interval_is_per_resource(tmp_path, monkeypatch):
    monkeypatch.setattr(rm, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(rm, "BURST_ROOT", tmp_path / "bursts")
    monkeypatch.setattr(rm.time, "time", lambda: 10_000.0)
    monkeypatch.setattr(rm, "_daily_count", lambda now, resource: 0)
    monitor = rm.Monitor(burst_seconds=2)
    monitor.last_burst = {"cpu": 9_500.0, "io": 0.0, "memory": 0.0}
    started: list[str] = []
    monkeypatch.setattr(
        rm, "run_burst", lambda trigger, seconds: started.append(trigger)
    )

    class ImmediateThread:
        def __init__(self, *, target, name, daemon):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(rm.threading, "Thread", ImmediateThread)
    specs = {spec.name: spec for spec in rm.TRIGGERS}
    monitor._start_burst(specs["cpu"])
    monitor._start_burst(specs["io"])
    assert started == ["psi-io"]


def test_suppression_notice_is_once_per_resource_reason_and_day(
    tmp_path, monkeypatch, caplog
):
    monkeypatch.setattr(rm, "STATE_ROOT", tmp_path)
    monitor = rm.Monitor(burst_seconds=2)
    spec = next(spec for spec in rm.TRIGGERS if spec.name == "cpu")
    with caplog.at_level("INFO", logger="binnacle.resource_monitor"):
        monitor._suppress_once(spec, "daily_cap", 1_790_660_000.0)
        monitor._suppress_once(spec, "daily_cap", 1_790_660_000.0)
        monitor._suppress_once(spec, "min_interval", 1_790_660_000.0)
    assert caplog.text.count("reason=daily_cap resource=cpu") == 1
    assert caplog.text.count("reason=min_interval resource=cpu") == 1
