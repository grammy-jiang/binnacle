"""r5 L1b (SD-52): the Darwin manager instructions disclose untracked sessions.

r5 L1 removes the routine descendants_unverified sentence from run_command
results; the fact stays in the Darwin owner=manager server instructions as
one short clause, within SD-33's 35-token disclosure budget (enforced in
tests/contracts/test_surface_tokens.py). Linux and the embedded Darwin owner
keep their instructions, and stop_job's description stays the Linux bytes.
The host is patched, so this runs on every host.
"""

import hashlib
import json
from pathlib import Path

import pytest

from binnacle import application
from tests.contracts.test_surface_tokens import SD52_CLAUSE, darwin_manager_disclosure

ROOT = Path(__file__).resolve().parents[3]
_LINUX_PIN = ROOT / "docs/os-independent-stage1-evidence/os0-raw-mcp-surface.json"
# Unchanged by SD-52: the Linux pin (test_tool_surface.INSTRUCTIONS_SHA256) and
# the embedded Darwin owner's text at R4 FINAL2 82195ad.
LINUX_SHA256 = "55cafa03a706b86aaab8d53b45030a76177f9da70767ca09de608d20573d5339"
EMBEDDED_SHA256 = "22cc54dc5d8f3e813c42d095250e06f0542439c448aa2c4e2a3d2be915041541"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _instructions(monkeypatch, system, owner):
    monkeypatch.setattr(application.platform, "system", lambda: system)
    return application._server_instructions(owner)


def test_manager_instructions_carry_the_clause_once(monkeypatch):
    text = _instructions(monkeypatch, "Darwin", "manager")
    assert text.count(SD52_CLAUSE) == 1
    # One clause between the fail-closed service note and the D-1 sentence.
    assert (
        f"{application.DARWIN_MANAGER_REQUIREMENT} {SD52_CLAUSE} "
        f"{application.DARWIN_JOBS_DISCLOSURE}"
    ) in text
    assert text.endswith(application.DARWIN_JOBS_DISCLOSURE)
    assert darwin_manager_disclosure().startswith(SD52_CLAUSE)
    assert len(text) <= 512  # first block self-contained (OpenAI guidance)


@pytest.mark.parametrize(
    ("system", "owner", "expected"),
    [
        ("Linux", None, LINUX_SHA256),
        ("Linux", "manager", LINUX_SHA256),
        ("Darwin", None, EMBEDDED_SHA256),
        ("Darwin", "embedded", EMBEDDED_SHA256),
    ],
)
def test_other_instructions_are_unchanged(monkeypatch, system, owner, expected):
    text = _instructions(monkeypatch, system, owner)
    assert _sha256(text) == expected
    assert "new session" not in text


def test_stop_job_description_stays_the_linux_bytes():
    from tests.contracts.surface_support import served

    tools, _ = served()
    stop_job = next(tool for tool in tools if tool.name == "stop_job")
    surface = json.loads(_LINUX_PIN.read_text())["profile_surfaces"]["default"]
    pin = next(tool for tool in surface["tools"] if tool["name"] == "stop_job")
    assert (stop_job.description or "").encode() == pin["description"].encode()
    assert "new session" not in pin["description"]
