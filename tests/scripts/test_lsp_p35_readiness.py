"""P3.5 bounded workspace indexing readiness without weakening gold checks."""

from __future__ import annotations

import asyncio

import pytest

from scripts.lsp_benchmark.corpus import synthetic
from scripts.lsp_benchmark.metrics import correct


def _gold_symbol_reply(case, root):
    file, start_line, start, end_line, end = case.locations[0]
    return [
        {
            "name": case.names[0],
            "location": {
                "uri": (root / file).as_uri(),
                "range": {
                    "start": {"line": start_line, "character": start},
                    "end": {"line": end_line, "character": end},
                },
            },
        }
    ]


@pytest.mark.asyncio
async def test_workspace_readiness_retries_until_exact_gold(tmp_path):
    from scripts.lsp_benchmark.native import await_workspace_symbol_readiness

    case = synthetic("small").cases[-1]
    responses = [[], _gold_symbol_reply(case, tmp_path)]

    async def retrieve():
        return responses.pop(0)

    attempts = await await_workspace_symbol_readiness(
        retrieve,
        lambda value: correct(case, value, tmp_path),
        deadline_s=1.0,
        interval_s=0.001,
    )
    assert attempts == 2 and responses == []


@pytest.mark.asyncio
async def test_workspace_readiness_timeout_does_not_claim_success():
    from scripts.lsp_benchmark.native import await_workspace_symbol_readiness

    async def never_ready():
        return []

    with pytest.raises(asyncio.TimeoutError):
        await await_workspace_symbol_readiness(
            never_ready,
            lambda value: bool(value),
            deadline_s=0.02,
            interval_s=0.001,
        )
