"""Deterministic P3.5 gold, aggregation, bounds and trust checks; no providers."""

import asyncio
import hashlib
import json

import pytest

from scripts.lsp_benchmark import __main__ as cli
from scripts.lsp_benchmark.corpus import synthetic, trusted_snapshot
from scripts.lsp_benchmark.metrics import correct, percentiles
from scripts.lsp_benchmark.runner import Options, experiment


def reply(case, root):
    locations = [
        {
            "uri": (root / file).as_uri(),
            "range": {
                "start": {"line": line, "character": char},
                "end": {"line": end_line, "character": end_char},
            },
        }
        for file, line, char, end_line, end_char in case.locations
    ]
    if case.operation == "hover":
        return {"contents": {"kind": "plaintext", "value": " ".join(case.names)}}
    if case.operation in ("document_symbols", "workspace_symbols"):
        return [
            {"name": name, "location": loc}
            for name, loc in zip(case.names, locations, strict=True)
        ]
    return locations


class FakeResources:
    def capture(self, roots, residents):
        pass

    def result(self):
        return {"tree_rss_peak_bytes": 100, "status": "observed"}


class FakeBackend:
    def __init__(self, tmp_path, instances=1, fault=None):
        self.roots = [tmp_path / str(i) for i in range(instances)]
        self.initialization = [2.0] * instances
        self.residents = instances
        self.fault = fault
        self.calls = 0
        self.closed = False
        self.active = self.peak = 0

    def processes(self):
        return []

    async def start(self, cases):
        if self.fault == "startup":
            raise ValueError("private /secret/file content")

    def supports(self, index, operation):
        return self.fault != "unsupported"

    async def query(self, index, case):
        self.calls += 1
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            # One deterministic scheduler turn, no clock sleep or process.
            ready = asyncio.get_running_loop().create_future()
            asyncio.get_running_loop().call_soon(ready.set_result, None)
            await ready
            if self.fault == "error":
                raise ValueError("private /secret/file content")
            if self.fault == "timeout":
                await asyncio.Event().wait()
            if self.fault == "incorrect":
                return []
            return reply(case, self.roots[index])
        finally:
            self.active -= 1

    async def close(self):
        self.closed = True
        return self.fault != "cleanup"


@pytest.mark.parametrize("scale,count", [("small", 3), ("medium", 131)])
def test_corpus_reproducible_and_disposable(tmp_path, scale, count):
    corpus = synthetic(scale)
    assert corpus.identity() == synthetic(scale).identity()
    assert corpus.identity()["file_count"] == count
    corpus.materialize(tmp_path / "fixture")
    assert cli.unchanged(tmp_path / "fixture", corpus.files)
    (tmp_path / "fixture" / "lib.py").write_text("changed")
    assert not cli.unchanged(tmp_path / "fixture", corpus.files)


def test_percentiles_nearest_rank_sample_size():
    assert percentiles([]) == {"p50": None, "p95": None, "p99": None}
    assert percentiles([1]) == {"p50": 1, "p95": 1, "p99": 1}
    assert percentiles(list(range(1, 101))) == {"p50": 50, "p95": 95, "p99": 99}


@pytest.mark.parametrize("operation", range(6))
def test_gold_is_content_and_location_based(tmp_path, operation):
    case = synthetic("small").cases[operation]
    assert correct(case, reply(case, tmp_path), tmp_path)
    assert not correct(case, [], tmp_path)
    assert not correct(case, {"private": "secret"}, tmp_path)
    if case.locations and case.operation not in (
        "document_symbols",
        "workspace_symbols",
    ):
        response = reply(case, tmp_path)
        response[0]["range"]["start"]["character"] += 1
        assert not correct(case, response, tmp_path)
        assert not correct(case, reply(case, tmp_path.parent), tmp_path)
        assert not correct(case, reply(case, tmp_path) * 2, tmp_path)


@pytest.mark.parametrize(
    "field,value",
    [
        ("repeats", 0),
        ("repeats", True),
        ("repeats", 1001),
        ("instances", 4),
        ("concurrency", 5),
        ("warmup", 0),
        ("deadline_s", float("nan")),
        ("total_s", float("inf")),
        ("sample_interval_s", 0.001),
    ],
)
def test_experiment_bounds(field, value):
    with pytest.raises(ValueError):
        Options(**{field: value})


@pytest.mark.asyncio
async def test_exact_warmup_repeats_concurrency_and_sanitized_aggregation(tmp_path):
    options = Options(repeats=7, warmup=2, instances=2, concurrency=3)
    backend = FakeBackend(tmp_path, instances=2)
    result = await experiment(
        backend, synthetic("small"), options, resources=FakeResources()
    )
    assert result["valid"] and backend.closed
    assert backend.calls == 6 * 2 * (7 + 2)
    assert backend.peak <= 3
    for row in result["operations"]:
        assert row["settling"]["correct"] == 4
        assert row["warm"]["samples"] == row["warm"]["correct"] == 14
        assert row["warm"]["correctness_rate"] == 1
        assert set(row["warm"]["response_ms"]) == {"p50", "p95", "p99"}
    serialized = json.dumps(result)
    assert str(tmp_path) not in serialized
    assert "greet" not in serialized and "file://" not in serialized


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault", ["startup", "error", "timeout", "incorrect", "cleanup", "unsupported"]
)
async def test_failures_never_rank_as_success_and_always_close(tmp_path, fault):
    backend = FakeBackend(tmp_path, fault=fault)
    corpus = synthetic("small")
    corpus.cases = corpus.cases[:1]
    result = await experiment(
        backend,
        corpus,
        Options(repeats=1, warmup=1, deadline_s=0.01),
        resources=FakeResources(),
    )
    assert not result["valid"] and backend.closed
    assert "/secret" not in json.dumps(result)
    if fault in ("error", "timeout", "incorrect"):
        assert (
            result["operations"][0]["budget_label"]
            == "invalid_correctness_or_incomplete"
        )
        assert result["operations"][0]["warm"]["correct_response_ms"]["p50"] is None
    if fault == "unsupported":
        assert backend.calls == 0


@pytest.mark.asyncio
async def test_budgets_label_observation_without_release_go(tmp_path):
    backend = FakeBackend(tmp_path)
    counter = iter(range(1000))
    result = await experiment(
        backend,
        synthetic("small"),
        Options(repeats=1, warmup=1, p95_budget_ms=1),
        resources=FakeResources(),
        clock=lambda: next(counter),
    )
    assert result["valid"]
    assert all(
        r["budget_label"] == "exceeds_provisional_budget" for r in result["operations"]
    )
    assert result["release_decision"] == "NOT_EVALUATED_READ_NO_GO"
    assert result["sample_grade"] == "smoke"


def manifest(tmp_path):
    root = tmp_path / "real"
    root.mkdir()
    content = b"def greet():\n    return 1\n"
    (root / "lib.py").write_bytes(content)
    spec = {
        "schema": 1,
        "revision": "a" * 40,
        "files": {"lib.py": hashlib.sha256(content).hexdigest()},
        "cases": [
            {
                "operation": "manager_definition",
                "file": "lib.py",
                "line": 0,
                "character": 4,
                "symbol": "greet",
                "locations": [["lib.py", 0, 4, 0, 9]],
            }
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(spec))
    return root, path, spec


def test_real_corpus_requires_exact_authorization_before_manifest_read(tmp_path):
    with pytest.raises(ValueError, match="trust_required"):
        trusted_snapshot(tmp_path / "absent", tmp_path / "absent.json", None)
    root, path, spec = manifest(tmp_path)
    before = (root / "lib.py").read_bytes()
    corpus = trusted_snapshot(root, path, root)
    corpus.materialize(tmp_path / "copy")
    assert corpus.kind == "trusted_real_snapshot"
    assert (root / "lib.py").read_bytes() == before
    assert corpus.revision == spec["revision"]


@pytest.mark.parametrize("change", ["hash", "traversal", "symlink", "gold", "revision"])
def test_real_corpus_rejects_unreviewed_inputs(tmp_path, change):
    root, path, spec = manifest(tmp_path)
    if change == "hash":
        spec["files"]["lib.py"] = "0" * 64
    elif change == "traversal":
        spec["files"] = {"../escape.py": "0" * 64}
    elif change == "symlink":
        (root / "alias.py").symlink_to(root / "lib.py")
        spec["files"] = {"alias.py": spec["files"]["lib.py"]}
    elif change == "gold":
        spec["cases"][0]["locations"] = []
    else:
        spec["revision"] = "/private/repository"
    path.write_text(json.dumps(spec))
    with pytest.raises(ValueError):
        trusted_snapshot(root, path, root)


@pytest.mark.parametrize(
    "args", [[], ["--run"], ["--run", "--quiet-host", "--real-root", "/private"]]
)
def test_cli_admission_does_not_launch(monkeypatch, args):
    def forbidden(*args, **kwargs):
        pytest.fail("attempted provider launch")

    monkeypatch.setattr(cli, "NativeBackend", forbidden)
    with pytest.raises(ValueError):
        cli.run(cli.parser().parse_args(args))


def test_cli_never_overwrites_existing_output(tmp_path):
    path = tmp_path / "result.json"
    path.write_text("preserve")
    assert cli.main(["--run", "--output", str(path)]) == 2
    assert path.read_text() == "preserve"


def test_future_profile_is_not_launch_authority(monkeypatch):
    monkeypatch.setattr(cli, "environment", dict)
    args = cli.parser().parse_args(["--run", "--quiet-host", "--provider", "clangd"])
    assert cli.run(args)["status"] == "profile_not_admitted"


def test_resource_sampling_deduplicates_children_and_retains_cpu(monkeypatch):
    from types import SimpleNamespace

    import psutil

    from scripts.lsp_benchmark.metrics import Resources

    class Process:
        def __init__(self, pid):
            self.pid = pid

        def children(self, recursive):
            return [Process(2)] if self.pid == 1 else []

        def create_time(self):
            return 100 + self.pid

        def memory_info(self):
            return SimpleNamespace(rss=10 * self.pid)

        def cpu_times(self):
            return SimpleNamespace(user=self.pid, system=0.5)

    monkeypatch.setattr(psutil, "Process", Process)
    metrics = Resources()
    metrics.capture([1, 2], 2)
    metrics.capture([1], 1)
    result = metrics.result()
    assert result["tree_rss_peak_bytes"] == 30
    assert result["observed_cpu_seconds"] == 4
    assert result["resident_instances_peak"] == 2
    assert result["process_count_peak"] == 2
    assert result["samples"] == 2


def test_missing_resource_observations_are_not_zero_rss(monkeypatch):
    import psutil

    from scripts.lsp_benchmark.metrics import Resources

    def missing(pid):
        raise psutil.NoSuchProcess(pid)

    monkeypatch.setattr(psutil, "Process", missing)
    metrics = Resources()
    metrics.capture([999], 1)
    assert metrics.result()["tree_rss_peak_bytes"] is None
    assert metrics.result()["sampling_errors"] == 1


@pytest.mark.asyncio
async def test_external_cancellation_still_closes_owned_backend(tmp_path):
    backend = FakeBackend(tmp_path, fault="timeout")
    task = asyncio.create_task(
        experiment(backend, synthetic("small"), Options(), resources=FakeResources())
    )
    # Explicit event-loop scheduling rather than clock sleeps.
    while backend.calls == 0:
        ready = asyncio.get_running_loop().create_future()
        asyncio.get_running_loop().call_soon(ready.set_result, None)
        await ready
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert backend.closed
    assert backend.active == 0


def test_provenance_checks_package_version_and_upstream_pin(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from scripts.lsp_benchmark import native

    package = tmp_path / "package"
    package.mkdir()
    (package / "dist").mkdir()
    for name in (
        "langserver.index.js",
        "dist/pyright.js",
        "dist/pyright-internal.js",
        "dist/vendor.js",
    ):
        (package / name).write_text("fixture")
    (package / "package.json").write_text(
        json.dumps({"name": "pyright", "version": "1.1.413"})
    )
    manifest = {
        "url": "https://github.com/grammy-jiang/multilspy.git",
        "vcs_info": {"commit_id": native.UPSTREAM_SHA},
    }
    monkeypatch.setattr(
        native,
        "distribution",
        lambda _: SimpleNamespace(
            read_text=lambda _: json.dumps(manifest),
            locate_file=lambda _: package / "package.json",
        ),
    )
    monkeypatch.setattr(
        native.shutil, "which", lambda _: str(package / "langserver.index.js")
    )
    monkeypatch.setattr(
        native.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="v22.0.0"),
    )
    result = native.provenance(package / "langserver.index.js")
    assert result["version"] == "1.1.413"
    assert str(package) not in json.dumps(result)
    manifest["vcs_info"]["commit_id"] = "bad"
    with pytest.raises(ValueError, match="provenance_mismatch"):
        native.provenance(package / "langserver.index.js")
    (package / "package.json").write_text(
        json.dumps({"name": "pyright", "version": "1.1.412"})
    )
    with pytest.raises(ValueError, match="version_mismatch"):
        native.provenance(package / "langserver.index.js")


def test_real_snapshot_refuses_project_configuration(tmp_path):
    root, path, spec = manifest(tmp_path)
    spec["files"]["pyrightconfig.json"] = "0" * 64
    path.write_text(json.dumps(spec))
    with pytest.raises(ValueError, match="python_sources_only"):
        trusted_snapshot(root, path, root)


def test_cli_missing_provider_reports_not_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "environment", dict)
    args = cli.parser().parse_args(
        ["--run", "--quiet-host", "--binary", str(tmp_path / "missing")]
    )
    assert cli.run(args)["status"] == "not_installed"


def test_cli_failures_are_sanitized_json(monkeypatch, capsys):
    def failure(args):
        raise RuntimeError("/private/path contains source secrets")

    monkeypatch.setattr(cli, "run", failure)
    assert cli.main(["--run"]) == 2
    output = capsys.readouterr().out
    assert json.loads(output)["status"] == "admission_or_execution_error"
    assert "/private" not in output and "secrets" not in output


@pytest.mark.asyncio
async def test_total_workload_deadline_cancels_request_and_closes(tmp_path):
    backend = FakeBackend(tmp_path, fault="timeout")
    result = await experiment(
        backend,
        synthetic("small"),
        Options(repeats=1, warmup=1, deadline_s=10, total_s=1),
        resources=FakeResources(),
    )
    assert result["status"] == "deadline_exceeded"
    assert result["valid"] is False
    assert backend.closed and backend.active == 0


@pytest.mark.parametrize("mutation", ["marker", "extra_file", "extra_directory"])
def test_snapshot_detects_provider_side_effects(tmp_path, mutation):
    corpus = synthetic("small")
    root = tmp_path / "copy"
    corpus.materialize(root)
    if mutation == "marker":
        (root / ".git").unlink()
    elif mutation == "extra_file":
        (root / "extra").write_text("unexpected provider output")
    else:
        (root / "cache").mkdir()
    assert not cli.unchanged(root, corpus.files)


@pytest.mark.asyncio
async def test_hidden_resident_restart_invalidates_warm_evidence(tmp_path):
    backend = FakeBackend(tmp_path)
    backend.initialization.append(2.0)
    result = await experiment(
        backend,
        synthetic("small"),
        Options(repeats=1, warmup=1),
        resources=FakeResources(),
    )
    assert result["status"] == "completed"
    assert not result["resident_reuse_verified"]
    assert not result["valid"]
