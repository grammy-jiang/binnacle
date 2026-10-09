"""Masking, sizing and snapshot files for tests/contracts/test_golden_outputs.py.

A recorded result has four fields: ``is_error``, ``content`` (the text
parts), ``structured`` (the structured content) and ``size``. Before
anything is compared, the values that change from run to run are masked:

- the test's tmp directory becomes ``<tmp>`` wherever a string holds it;
- each job id becomes ``<job-1>``, ``<job-2>`` ... in order of appearance,
  so the snapshot still shows which calls talk about the same job;
- the numbers under VOLATILE_KEYS (timestamps, durations, process ids)
  become ``"<number>"``;
- a decimal number of seconds in the text ("exited 0 in 0.004 s") becomes
  ``<s>``.

``size`` is the size budget: the structured bytes (compact JSON, the way
the server's tool_result line counts ``structured_bytes``) and the tokens of
the text parts plus that JSON (o200k_base, as the tokenizer telemetry
counts). Both are measured on the masked result, so they do not depend on
the machine. Strings longer than LONG_TEXT_CHARS are stored as their length,
sha256, head and tail to keep the files readable; they count in full.

Set BINNACLE_UPDATE_SNAPSHOTS=1 to write the snapshots instead of comparing
them. Review the diff before committing it.
"""

import hashlib
import json
import os
import re
from functools import lru_cache
from pathlib import Path

import pytest

from binnacle.observability.token_telemetry import _load_encoding

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"
UPDATE_ENV = "BINNACLE_UPDATE_SNAPSHOTS"
ENCODING = "o200k_base"
VOLATILE_KEYS = frozenset(
    {
        "started_at",
        "ended_at",
        "runtime_s",
        "duration_s",
        "waited_s",
        "last_output_age_s",
        "pid",
        "pgid",
        "etime_s",
        "cpu_s",
    }
)
LONG_TEXT_CHARS = 400
_SECONDS = re.compile(r"\b\d+\.\d+(?= s\b)")


@lru_cache(maxsize=1)
def _encoder():
    return _load_encoding(ENCODING)


def compact(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


class Masker:
    """Masks one test's results; job labels are shared across its calls."""

    def __init__(self, tmp: Path) -> None:
        roots = {str(tmp), str(tmp.resolve())}
        self._roots = sorted(roots, key=len, reverse=True)
        self._jobs: dict[str, str] = {}

    def _text(self, text: str) -> str:
        for root in self._roots:
            text = text.replace(root, "<tmp>")
        for job_id, label in self._jobs.items():
            text = text.replace(job_id, label)
        return text

    def value(self, value: object, key: str | None = None) -> object:
        if isinstance(value, dict):
            job_id = value.get("job_id")
            if isinstance(job_id, str) and job_id not in self._jobs:
                self._jobs[job_id] = f"<job-{len(self._jobs) + 1}>"
            return {k: self.value(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [self.value(item) for item in value]
        if key in VOLATILE_KEYS and isinstance(value, (int, float)):
            return "<number>"
        if isinstance(value, str):
            return self._text(value)
        return value

    def record(self, result) -> dict:
        """The masked result with its size budget."""
        structured = self.value(result.structured_content)
        text = "".join(getattr(part, "text", "") for part in result.content)
        content = _SECONDS.sub("<s>", self._text(text))
        payload = compact(structured) if structured is not None else ""
        tokens = sum(len(_encoder().encode(part)) for part in (content, payload))
        return {
            "is_error": result.is_error,
            "content": content,
            "structured": _shorten(structured),
            "size": {"structured_bytes": len(payload.encode()), "tokens": tokens},
        }


def _shorten(value: object) -> object:
    if isinstance(value, dict):
        return {k: _shorten(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_shorten(item) for item in value]
    if isinstance(value, str) and len(value) > LONG_TEXT_CHARS:
        return {
            "long_text": {
                "chars": len(value),
                "sha256": hashlib.sha256(value.encode()).hexdigest(),
                "head": value[:40],
                "tail": value[-40:],
            }
        }
    return value


def check(name: str, recorded: dict) -> None:
    """Compare with snapshots/<name>.json, or write it in update mode."""
    path = SNAPSHOT_DIR / f"{name}.json"
    if os.environ.get(UPDATE_ENV) == "1":
        text = json.dumps(recorded, indent=2, ensure_ascii=False) + "\n"
        if not path.exists() or path.read_text() != text:
            path.write_text(text)
        return
    if not path.exists():
        pytest.fail(f"no snapshot {path.name}; run with {UPDATE_ENV}=1 to create it")
    expected = json.loads(path.read_text())
    got, budget = recorded["size"], expected["size"]
    assert got == budget, (
        f"{name}: size changed from {budget} to {got}; if intended, rerun with "
        f"{UPDATE_ENV}=1 and give the reason in the commit"
    )
    assert recorded == expected
