"""Fake-only benchmark correctness and reproducibility, never provider performance."""

import copy
import json

import pytest

from tests.fixtures.lsp import raw_benchmark as bench


def test_resident_gold_and_repeatable_identity(tmp_path):
    first = bench.run(tmp_path / "first.json")
    second = bench.run(tmp_path / "second.json")
    for result in (first, second):
        assert result["valid"] and result["gold_verified"]
        assert result["correct_samples"] == 30
        assert len(result["samples"]) == 30
        assert result["first_request"]["correct"]
        assert result["warm_ms"] == bench.percentiles(
            [s["latency_ms"] for s in result["samples"]]
        )
        assert result["cold_initialize_ms"] > 0
        assert result["cleanup_verified"]
        assert result["resources"]["status"] == "skipped"
        assert result["settling"]["indexed"] is None
        assert not bench.Path(result["execution"]["cwd"]).exists()
        assert result["evidence"] == "fake-only"
    assert first["identity"] == second["identity"]
    assert first["execution"]["pid"] != second["execution"]["pid"]
    assert json.loads((tmp_path / "first.json").read_text()) == first
    assert "# Synthetic" not in (tmp_path / "first.json").read_text()


@pytest.mark.parametrize("mutation", ["missing", "wrong", "shape"])
def test_invalid_gold_never_times(tmp_path, mutation):
    manifest = json.loads(bench.MANIFEST.read_text())
    if mutation == "missing":
        del manifest["gold"]
    elif mutation == "wrong":
        manifest["gold"]["range"]["start"]["line"] = 999
    else:
        manifest["gold"] = [manifest["gold"]]
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    result = bench.run(tmp_path / "invalid.json", manifest_path=path)
    assert not result["valid"]
    assert result["samples"] == []
    assert "warm_ms" not in result
    assert "execution" not in result


@pytest.mark.parametrize(
    "fault", ["hang-initialize", "crash-initialize", "crash-request"]
)
def test_failure_is_not_fast_success(tmp_path, fault):
    result = bench.run(tmp_path / "failed.json", fault=fault, deadline=0.1)
    assert not result["valid"] and not result["gold_verified"]
    assert result["samples"] == []
    assert "warm_ms" not in result


@pytest.mark.parametrize("bad", [None, [], {"uri": "file:///wrong.py"}])
def test_semantic_assertion_precedes_sample(bad):
    manifest = bench.load_manifest(bench.MANIFEST)

    class WrongPeer:
        def send(self, message):
            pass

        def receive(self, timeout):
            return {"jsonrpc": "2.0", "id": 2, "result": copy.deepcopy(bad)}

        def validate_response(self, response, number):
            assert response["id"] == number

    with pytest.raises(ValueError, match="incorrect semantic"):
        bench.semantic(WrongPeer(), manifest, 2, 0.1)


def test_limits_and_destination(tmp_path):
    with pytest.raises(ValueError, match="outside source"):
        bench.run(bench.ROOT / "forbidden.json")
    with pytest.raises(ValueError, match="bounded run"):
        bench.run(tmp_path / "short.json", repetitions=29)
    with pytest.raises(ValueError, match="explicit fake"):
        bench.run(tmp_path / "provider.json", fault="pyright")
    assert bench.percentiles(list(range(1, 101))) == {"p50": 50, "p95": 95, "p99": 99}
    with pytest.raises(ValueError):
        bench.percentiles([])
