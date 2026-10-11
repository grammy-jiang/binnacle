"""r5 L2: Darwin manager job semantics equal Linux (P5-L2, SD-50, SD-41).

* Authority-UNKNOWN records keep the D-1 text (SD-41).
* The job workdir is echoed in the caller's form (L3's ``caller_form`` rule,
  imported, no firmlink table) while the job spawns in the resolved directory.
* Also hosts L1's routine-text pin, moved here at the module-size limit.
"""

import json
import platform
import re
import threading
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from binnacle.config import RootsSettings
from binnacle.features.commands import command_backend as cb
from binnacle.features.commands.tools import job_status as js
from binnacle.features.commands.tools import run_command as rc
from binnacle.platform import composition
from binnacle.platform.contracts.process_contracts import OwnedJobExit
from binnacle.platform.darwin import job_manager_service as svc
from tests.platform.darwin.test_durable_tool_wiring import _manager
from tests.platform.darwin.test_job_manager_service import (
    ReferenceOwner,
    manager_for,
    meta_of,
    req,
)
from tests.unit.tools.test_r4_cov_run_command_server import manager_backend

_DARWIN = pytest.mark.skipif(
    platform.system() != "Darwin", reason="native Darwin composition"
)


def _record(**extra):
    return {
        "command": "sleep 60",
        "workdir": "/tmp",
        "pid": 7,
        "started_at": 1.0,
        **extra,
    }


@pytest.mark.parametrize(
    "exited,want",
    [
        (OwnedJobExit("j", 3, None, "normal_exit"), (3, None, "normal_exit")),
        (OwnedJobExit("j", None, 15, "signal"), (None, 15, "signal")),
        (OwnedJobExit("j", None, 15, "stop_requested"), (None, 15, "signal")),
    ],
)
def test_other_exits_keep_their_status(exited, want):
    meta = svc._exit_meta(_record(), exited)
    assert (meta["exit_code"], meta.get("signal"), meta["termination_reason"]) == want


def _alias(tmp_path):
    real = tmp_path / "real"
    (real / "sub").mkdir(parents=True)
    alias = tmp_path / "alias"
    alias.symlink_to(real)
    return real.resolve(), alias


def test_manager_records_caller_form_and_spawns_in_resolved_dir(tmp_path):
    real, alias = _alias(tmp_path)
    manager, halt = manager_for(ReferenceOwner(), tmp_path / "jobs"), threading.Event()
    reaper = threading.Thread(target=manager.reap_forever, args=(halt,))
    reaper.start()
    try:
        reply = manager.handle(req(alias / "sub", "pwd -P", wait=5))
        assert reply["ok"] and reply["state"] == "exited"
        job_id = reply["job_id"]
        assert meta_of(manager.jobs_dir, job_id)["workdir"] == str(alias / "sub")
        out = (manager.jobs_dir / job_id / "out.log").read_text().strip()
        assert out == str(real / "sub")  # spawned in the resolved directory
        missing = manager.handle(req(alias / "nope"))
        assert missing["error"].endswith(f"workdir is not a directory: {alias}/nope")
    finally:
        halt.set()
        reaper.join()
        manager.close()


@pytest.mark.parametrize("host", ["darwin", "linux"])
def test_missing_workdir_message_spells_caller_form_on_macos_only(
    tmp_path, monkeypatch, host
):
    real, alias = _alias(tmp_path)
    monkeypatch.setattr(composition, "host_os_family", lambda: host)
    roots = RootsSettings(default_root=alias)
    with pytest.raises(ToolError) as caught:
        rc.run_command_impl(
            "true",
            "nope",
            1,
            False,
            None,
            roots=roots,
            backend=manager_backend(tmp_path),
        )
    shown = alias if host == "darwin" else real
    assert f"workdir is not a directory: {shown}/nope. " in str(caught.value)


@_DARWIN
@pytest.mark.parametrize("host", ["darwin", "linux"])
def test_manager_job_echoes_caller_form_workdir(tmp_path, monkeypatch, host):
    settings, _, backend = _manager(tmp_path)
    real, alias = _alias(tmp_path)
    monkeypatch.setattr(composition, "host_os_family", lambda: host)
    settings.roots.default_root = alias  # configured through the alias
    shown = str(alias / "sub" if host == "darwin" else real / "sub")
    result = rc.run_command_impl(
        "pwd -P", "sub", 5, False, None, roots=settings.roots, backend=backend
    )
    payload = result.structured_content
    assert payload["workdir"] == shown
    assert payload["output"].strip() == str(real / "sub")  # ran in the real dir
    status = js.job_status_impl(payload["job_id"], 10, backend=backend)
    assert status.structured_content["workdir"] == shown


@_DARWIN
def test_authority_unknown_record_keeps_d1_text(tmp_path):
    settings, root, backend = _manager(tmp_path)
    started = rc.run_command_impl(
        "RUNNING", str(root), 1, False, None, roots=settings.roots, backend=backend
    )
    job_id = started.structured_content["job_id"]
    backend.client.lose_owner(job_id)  # owner_restart reason, authority UNKNOWN
    text = js.job_status_impl(job_id, 10, backend=backend).content[0].text
    assert text == f"Job {job_id} state unknown: {cb.DARWIN_OWNER_LOST_NOTE}."


# Moved unchanged from test_durable_tool_wiring.py (r5 L1), which had reached
# the 500-line module-size limit after the r5/parity merge.
@_DARWIN
def test_routine_result_text_is_byte_identical_to_linux(tmp_path):
    """SD-50 r5 L1: foreground, yielded-job and background text equal Linux."""
    snapshots = Path(__file__).parents[2] / "contracts" / "snapshots"
    settings, root, backend = _manager(tmp_path)

    def text(name, command, wait=5, background=False):
        result = rc.run_command_impl(
            command,
            str(root),
            wait,
            background,
            None,
            roots=settings.roots,
            backend=backend,
        )
        job_id = result.structured_content["job_id"]
        got = str(result.content[0].text).replace(job_id, "<job-1>")
        expected = json.loads((snapshots / f"{name}.json").read_text())["content"]
        return re.sub(r"\b\d+\.\d+(?= s\b)", "<s>", got).encode(), expected.encode()

    for got, linux in (
        text("run_command-fast", "printf 'hello golden\\n'"),
        text("run_command-job", "RUNNING", wait=1),
        text("run_command-background", "RUNNING", background=True),
    ):
        assert got == linux
