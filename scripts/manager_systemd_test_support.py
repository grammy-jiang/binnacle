"""Internal support for an EXPLICIT standalone D1 systemd rehearsal.

This is NOT a pytest test: tests/conftest.py prohibits host modifications.
Imported only by scripts/rehearse_manager_systemd_lifecycle.py after opt-in.
Temporary unit names are checked before ever calling `systemctl stop`.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from binnacle.features.commands import job_client, jobs
from scripts.manager_systemd_units import (
    _cleanup_own_unit,
    _expect,
    _fixture,
    _start_disposable_manager_unit,
    _start_job,
    _unit_setting,
    _wait_for,
)
from tests.integration.test_job_manager_v2 import _pinned_fd, _send


def check_v1_to_v2_then_v1_rollback_with_external_ingress_fenced_by_test_client(
    tmp_path: Path,
) -> dict:
    """Isolated first-upgrade rehearsal; deliberately cannot prove live ingress freeze.

    The legacy v1 Manager has NO pause RPC. This test owns its only client
    and can withhold further calls while a disposable job drains. It then
    upgrades to opt-in v2 and rolls back to the frozen original source.
    Critically, after rollback the original v1 accepts starts even while the
    v2's private durable pause marker remains. No false production GO.
    """
    unit, root, run, store, source_v2 = _fixture(tmp_path)
    source_v1 = Path(__file__).resolve().parents[1].parent / "binnacle" / "src"
    _expect(
        source_v1.joinpath("binnacle/features/commands/job_manager.py").is_file(),
        'source_v1.joinpath("binnacle/features/commands/job_manager.py").is_file()',
    )
    _expect(
        not source_v1.joinpath("binnacle/features/commands/job_manager_v2.py").exists(),
        'not source_v1.joinpath(         "binnacle/features/commands/job_manager_v2.py"     ).exists()',
    )
    v2_unit = f"binnacle-d1c-isolated-{uuid.uuid4().hex[:12]}.service"
    rollback_unit = f"binnacle-d1c-isolated-{uuid.uuid4().hex[:12]}.service"
    units = (unit, v2_unit, rollback_unit)
    try:
        _start_disposable_manager_unit(
            unit=unit,
            root=root,
            run=run,
            store=store,
            source=source_v1,
            v2_enabled=False,
        )
        _expect(
            not (run / "start-v2.sock").exists(), 'not (run / "start-v2.sock").exists()'
        )
        _expect(
            job_client.ping(run / "legacy.sock")["version"] == 1,
            'job_client.ping(run / "legacy.sock")["version"] == 1',
        )
        started = job_client.start(
            run / "legacy.sock",
            command="cat marker; sleep 0.3; echo V1-COMPLETE",
            workdir=root,
            stdin=None,
            wait_seconds=0.0,
            call_id="v1-first-upgrade-job",
        )
        _expect(started["ok"], 'started["ok"]')
        jid = started["job_id"]
        _expect(
            _wait_for(lambda: (store / jid / "meta.json").exists(), timeout=5),
            '_wait_for(lambda: (store / jid / "meta.json").exists(), timeout=5)',
        )
        # Ingress freeze is SIMULATED by the only test client withholding any
        # new calls; there is no server-side fence in this original v1 code.
        _expect(
            _wait_for(
                lambda: (
                    "exit_code" in json.loads((store / jid / "meta.json").read_text())
                ),
                timeout=6,
            ),
            '_wait_for(             lambda: "exit_code" in json.loads((store / jid / "meta.json").read_text()),             timeout=6,         )',
        )
        old_meta = json.loads((store / jid / "meta.json").read_text())
        _expect(old_meta["exit_code"] == 0, 'old_meta["exit_code"] == 0')
        _expect(
            (store / jid / "out.log").read_text()
            == "ISOLATED-CGROUP-ONLY\nV1-COMPLETE\n",
            '(             store / jid / "out.log"         ).read_text() == "ISOLATED-CGROUP-ONLY\\nV1-COMPLETE\\n"',
        )
        # Check old unit's delegated owner children are drained before stop.
        old_cgroup = _unit_setting(unit, "ControlGroup")
        for child in (Path("/sys/fs/cgroup") / old_cgroup.lstrip("/")).iterdir():
            if child.name.startswith("job-"):
                events = (child / "cgroup.events").read_text()
                _expect("populated 0" in events, (child, events))
        _cleanup_own_unit(unit)
        _expect(
            _unit_setting(unit, "ActiveState") in ("inactive", "failed"),
            '_unit_setting(unit, "ActiveState") in ("inactive", "failed")',
        )
        # Now a different owner generation with v2 is deployed on the *same*
        # private paths and durable spool. A production release still needs
        # its own ingress admission control approval.
        _start_disposable_manager_unit(
            unit=v2_unit, root=root, run=run, store=store, source=source_v2
        )
        _expect(
            job_client.ping(run / "legacy.sock")["version"] == 1,
            'job_client.ping(run / "legacy.sock")["version"] == 1',
        )
        _expect(
            json.loads((store / jid / "meta.json").read_text())["exit_code"] == 0,
            'json.loads((store / jid / "meta.json").read_text())["exit_code"] == 0',
        )
        nonce = uuid.uuid4().hex
        paused = _send(
            run / "start-v2.sock",
            {"version": 2, "op": "pause_starts", "nonce": nonce},
            (),
        )
        _expect(
            paused["ok"] and paused["safe_to_stop"] and paused["owner_cgroup_verified"],
            paused,
        )
        _cleanup_own_unit(v2_unit)
        # This is the negative rollback proof: the legacy process ignores
        # the durable marker and will start a command if external ingress is
        # re-opened too early. It only writes to the disposable fixture.
        _start_disposable_manager_unit(
            unit=rollback_unit,
            root=root,
            run=run,
            store=store,
            source=source_v1,
            v2_enabled=False,
        )
        _expect(
            not (run / "start-v2.sock").exists(), 'not (run / "start-v2.sock").exists()'
        )
        _expect(
            (store.parent / "v2-start-receipts" / "starts-paused").exists(),
            '(store.parent / "v2-start-receipts" / "starts-paused").exists()',
        )
        despite_pause = job_client.start(
            run / "legacy.sock",
            command="cat marker",
            workdir=root,
            stdin=None,
            wait_seconds=2.0,
            call_id="unsafe-old-v1-ignores-pause",
        )
        _expect(despite_pause["ok"], 'despite_pause["ok"]')
        _expect(
            (store / despite_pause["job_id"] / "out.log").read_text()
            == "ISOLATED-CGROUP-ONLY\n",
            '(             store / despite_pause["job_id"] / "out.log"         ).read_text() == "ISOLATED-CGROUP-ONLY\\n"',
        )
        return {
            "first_upgrade_v1_source_is_original_production_checkout": True,
            "initial_v1_drain_then_independent_v2_start_success": True,
            "existing_v1_job_log_and_exit_survive_v2_start": True,
            "v2_pause_proves_empty_owner_tree_before_rollback": True,
            "rollback_legacy_v1_ignores_durable_v2_pause": True,
            "external_ingress_freeze_only_simulated_in_test": True,
            "production_cutover_approved": False,
        }
    finally:
        for candidate in reversed(units):
            _cleanup_own_unit(candidate)


def check_control_group_stop_terminates_active_job(tmp_path: Path) -> dict:
    unit, root, run, store, source = _fixture(tmp_path)
    try:
        _start_disposable_manager_unit(
            unit=unit, root=root, run=run, store=store, source=source
        )
        response = _start_job(
            root,
            run,
            "printf 'ACTIVE-START\\n'; sleep 30; printf 'ACTIVE-END\\n'",
            "d1-isolated-active-job",
        )
        job = response["job_id"]
        _expect(
            _wait_for(lambda: (store / job / "meta.json").exists(), timeout=6),
            '_wait_for(lambda: (store / job / "meta.json").exists(), timeout=6)',
        )
        meta = json.loads((store / job / "meta.json").read_text())
        pid = meta["pid"]
        _expect(
            jobs._PROCESS_BACKEND.alive(pid, meta.get("starttime")),
            'jobs._PROCESS_BACKEND.alive(pid, meta.get("starttime"))',
        )
        manager_cgroup = _unit_setting(unit, "ControlGroup")

        # The shell wrapper joins its per-job cgroup *after* Python Popen
        # returns. Inspect after the attach, not before the asynchronous
        # bootstrap has had a chance to write cgroup.procs.
        def in_job_cgroup() -> bool:
            try:
                live = Path(f"/proc/{pid}/cgroup").read_text().split("::", 1)[1].strip()
            except (FileNotFoundError, IndexError):
                return False
            return live.startswith(manager_cgroup + "/job-")

        _expect(
            _wait_for(in_job_cgroup, timeout=3),
            (
                manager_cgroup,
                Path(f"/proc/{pid}/cgroup").read_text(),
            ),
        )
        _expect(
            _wait_for(
                lambda: "ACTIVE-START" in (store / job / "out.log").read_text(),
                timeout=5,
            ),
            '_wait_for(             lambda: "ACTIVE-START" in (store / job / "out.log").read_text(), timeout=5         )',
        )
        _cleanup_own_unit(unit)
        _expect(
            _wait_for(
                lambda: not jobs._PROCESS_BACKEND.alive(pid, meta.get("starttime")),
                timeout=5,
            ),
            '_wait_for(             lambda: not jobs._PROCESS_BACKEND.alive(pid, meta.get("starttime")),             timeout=5,         )',
        )
        log = (store / job / "out.log").read_text()
        _expect(
            "ACTIVE-START" in log and "ACTIVE-END" not in log,
            '"ACTIVE-START" in log and "ACTIVE-END" not in log',
        )
        # Some owner reapers can record SIGTERM before systemd finishes stop,
        # while others have no time to persist final metadata. Neither result
        # constitutes successful execution or a safe active-job upgrade.
        current = json.loads((store / job / "meta.json").read_text())
        _expect(current.get("exit_code") != 0, current)
        _expect(current.get("signal") in (None, 15), current)
        return {
            "control_group_matches_isolated_unit": True,
            "child_was_running_when_stop_requested": True,
            "active_job_terminated_before_completion": True,
            "signal_recorded": current.get("signal"),
            "last_marker_missing": True,
            "metadata_exit_code": current.get("exit_code"),
        }
    finally:
        _cleanup_own_unit(unit)


def check_untracked_job_cgroup_refuses_unsafe_stop(tmp_path: Path) -> dict:
    """Lost/corrupt job metadata must not hide a still-populated cgroup."""
    unit, root, run, store, source = _fixture(tmp_path)
    try:
        _start_disposable_manager_unit(
            unit=unit, root=root, run=run, store=store, source=source
        )
        reply = _start_job(
            root,
            run,
            "printf 'ORPHAN-START\n'; sleep 15; printf 'ORPHAN-END\n'",
            "d1-isolated-orphan-job-group",
        )
        job_id = reply["job_id"]
        meta_path = store / job_id / "meta.json"
        _expect(
            _wait_for(meta_path.exists, timeout=5),
            "_wait_for(meta_path.exists, timeout=5)",
        )
        meta = json.loads(meta_path.read_text())
        pid = meta["pid"]
        service_cgroup = _unit_setting(unit, "ControlGroup")

        def in_leaf():
            try:
                actual = (
                    Path(f"/proc/{pid}/cgroup").read_text().split("::", 1)[1].strip()
                )
            except (OSError, IndexError):
                return False
            return actual == service_cgroup + "/job-" + job_id

        _expect(
            _wait_for(in_leaf, timeout=4),
            "test child never entered delegated leaf cgroup",
        )
        # Simulate data-store loss from an interrupted write/prune, ONLY in
        # this unique disposable job store; do not touch any live job store.
        meta_path.unlink()
        nonce = uuid.uuid4().hex
        paused = _send(
            run / "start-v2.sock",
            {"version": 2, "op": "pause_starts", "nonce": nonce},
            (),
        )
        _expect(
            paused["ok"] and paused["starts_paused"],
            'paused["ok"] and paused["starts_paused"]',
        )
        _expect(
            paused["owner_cgroup_verified"] is True,
            'paused["owner_cgroup_verified"] is True',
        )
        _expect(not paused["safe_to_stop"], 'not paused["safe_to_stop"]')
        _expect(
            {"job_id": job_id, "state": "job_cgroup_populated"}
            in paused["active_jobs"],
            paused,
        )
        return {
            "untracked_active_process_detected_in_cgroup": True,
            "missing_job_metadata_not_misclassified_safe": True,
        }
    finally:
        _cleanup_own_unit(unit)


def check_completed_job_is_preserved_on_owner_stop(tmp_path: Path) -> dict:
    """Active job -> pause v1+v2 -> drain -> stop -> restart paused -> resume."""
    unit, root, run, store, source = _fixture(tmp_path)
    nonce = uuid.uuid4().hex
    try:
        _start_disposable_manager_unit(
            unit=unit, root=root, run=run, store=store, source=source
        )
        response = _start_job(
            root,
            run,
            "cat marker; sleep 0.6; printf 'DRAIN-COMPLETE\n'",
            "d1-isolated-completed-job",
        )
        job = response["job_id"]
        _expect(
            _wait_for(lambda: (store / job / "meta.json").exists(), timeout=6),
            '_wait_for(lambda: (store / job / "meta.json").exists(), timeout=6)',
        )
        # A single owner-wide lock ensures the fence is committed *after*
        # any earlier start has written its durable job metadata, and before
        # any later v1/v2 start is admitted.
        pause_req = {"version": 2, "op": "pause_starts", "nonce": nonce}
        initial = _send(run / "start-v2.sock", pause_req, ())
        _expect(
            initial["ok"] and initial["starts_paused"],
            'initial["ok"] and initial["starts_paused"]',
        )
        # Immediately after Popen the shell may still be moving out of the
        # manager subgroup into its job cgroup. Such a transitional snapshot
        # must be fail-closed; verified clean cgroups are required *later*,
        # after the job and all descendants have actually drained.
        _expect(initial["safe_to_stop"] is False, 'initial["safe_to_stop"] is False')
        # The initial list may also contain an honest owner-cgroup-unverified
        # entry while the shell moves into the per-job delegated cgroup.
        _expect(job in {j["job_id"] for j in initial["active_jobs"]}, initial)
        try:
            job_client.start(
                run / "legacy.sock",
                command="cat marker",
                workdir=root,
                stdin=None,
                wait_seconds=1.0,
                call_id="must-be-denied-v1",
            )
        except job_client.JobManagerError:
            pass
        else:
            raise AssertionError("v1 admitted a job after global pause")
        denied_fd = _pinned_fd(root)
        try:
            refused_v2 = _send(
                run / "start-v2.sock",
                {
                    "version": 2,
                    "op": "start",
                    "workdir": str(root),
                    "workdir_fd": True,
                    "command": "cat marker",
                    "stdin": None,
                    "wait_seconds": 0.0,
                    "call_id": "must-be-denied-v2",
                },
                (denied_fd,),
            )
        finally:
            os.close(denied_fd)
        _expect(refused_v2["ok"] is False, 'refused_v2["ok"] is False')
        _expect(
            len([d for d in store.iterdir() if d.is_dir()]) == 1,
            "len([d for d in store.iterdir() if d.is_dir()]) == 1",
        )
        _expect(
            _wait_for(
                lambda: (
                    "exit_code" in json.loads((store / job / "meta.json").read_text())
                ),
                timeout=8,
            ),
            "owner has not durably recorded job completion",
        )
        before = json.loads((store / job / "meta.json").read_text())
        _expect(before["exit_code"] == 0, 'before["exit_code"] == 0')
        ready = _send(run / "start-v2.sock", pause_req, ())
        _expect(
            ready["ok"] and ready["safe_to_stop"] and not ready["active_jobs"], ready
        )
        _expect(ready["owner_cgroup_verified"] is True, ready)
        _cleanup_own_unit(unit)
        after = json.loads((store / job / "meta.json").read_text())
        _expect(after["exit_code"] == 0, 'after["exit_code"] == 0')
        _expect(
            (store / job / "out.log").read_text().endswith("DRAIN-COMPLETE\n"),
            '(store / job / "out.log").read_text().endswith("DRAIN-COMPLETE\\n")',
        )
        # A new Manager process using the SAME state root must still be
        # paused. A release only resumes on an explicit authorized nonce.
        after_unit = f"binnacle-d1c-isolated-{uuid.uuid4().hex[:12]}.service"
        try:
            _start_disposable_manager_unit(
                unit=after_unit, root=root, run=run, store=store, source=source
            )
            state_after_restart = _send(run / "start-v2.sock", pause_req, ())
            _expect(state_after_restart["ok"], 'state_after_restart["ok"]')
            _expect(
                state_after_restart["safe_to_stop"],
                'state_after_restart["safe_to_stop"]',
            )
            _expect(
                state_after_restart["owner_cgroup_verified"] is True,
                state_after_restart,
            )
            _expect(
                state_after_restart["starts_paused"],
                'state_after_restart["starts_paused"]',
            )
            try:
                job_client.start(
                    run / "legacy.sock",
                    command="cat marker",
                    workdir=root,
                    stdin=None,
                    wait_seconds=1.0,
                    call_id="must-remain-paused",
                )
            except job_client.JobManagerError:
                pass
            else:
                raise AssertionError("v1 reopened after Manager restart without resume")
            resumed = _send(
                run / "start-v2.sock",
                {"version": 2, "op": "resume_starts", "nonce": nonce},
                (),
            )
            _expect(
                resumed["ok"] and not resumed["starts_paused"],
                'resumed["ok"] and not resumed["starts_paused"]',
            )
            accepted = job_client.start(
                run / "legacy.sock",
                command="cat marker",
                workdir=root,
                stdin=None,
                wait_seconds=2.0,
                call_id="authorized-after-resume",
            )
            _expect(accepted["ok"] is True, 'accepted["ok"] is True')
            new_job = accepted["job_id"]
            _expect(
                (store / new_job / "out.log").read_text() == "ISOLATED-CGROUP-ONLY\n",
                '(store / new_job / "out.log").read_text() == "ISOLATED-CGROUP-ONLY\\n"',
            )
        finally:
            _cleanup_own_unit(after_unit)
        return {
            "owner_paused_with_active_job": True,
            "owner_cgroup_tree_verified_at_active_drain_and_restart": True,
            "v1_and_v2_starts_rejected_during_drain": True,
            "completed_job_exit_code_preserved": 0,
            "completed_job_final_log_retained": True,
            "paused_state_survived_manager_stop_and_new_manager_process": True,
            "legacy_v1_reopened_only_after_explicit_v2_resume": True,
        }
    finally:
        _cleanup_own_unit(unit)
