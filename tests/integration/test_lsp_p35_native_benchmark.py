"""Tiny optional native smoke; no default provider execution or timing proof."""

import os
from pathlib import Path

import pytest

from scripts.lsp_benchmark.__main__ import parser, run


def test_p35_real_pyright_synthetic_smoke():
    if os.getenv("BINNACLE_P35_NATIVE_SMOKE") != "1":
        pytest.skip(
            "set BINNACLE_P35_NATIVE_SMOKE=1 and PYRIGHT_LSP_TEST_BIN explicitly"
        )
    binary = os.environ.get("PYRIGHT_LSP_TEST_BIN")
    if not binary or not Path(binary).is_file():
        pytest.fail("opted-in real Pyright test needs an explicit installed binary")
    result = run(
        parser().parse_args(
            [
                "--run",
                "--binary",
                binary,
                "--repeats",
                "1",
                "--warmup",
                "1",
                "--total-s",
                "40",
            ]
        )
    )
    assert result["valid"], result
    assert result["cleanup_verified"] and result["snapshot_unchanged"]
    assert result["resources"]["tree_rss_peak_bytes"] > 0
    assert result["initialize_samples"] == 1
    assert result["authoritative_timings"] is False
    assert all(row["warm"]["correct"] == 1 for row in result["operations"])
