"""Bounded lifecycle for explicitly test-owned launchd user services.

A live object remembers only a bootstrap it performed successfully. It never
adopts labels from a plist/marker or boots out somebody else's registration.
Durable-manager mutations remain unavailable: the frozen interface supplies no
atomic quiet/admission gate. Probe/frontend teardown proves registration,
observed leader exit and socket absence, not escaped-descendant containment.
"""

from __future__ import annotations

import hashlib
import os
import plistlib
import re
import select
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

from binnacle.platform.contracts.capability_contracts import (
    AuthorityUnknown,
    Capability,
    CapabilityState,
    CapabilityUnavailable,
    NativeCapabilityError,
)
from binnacle.platform.contracts.native_service_contracts import (
    ServiceLease,
    ServicePlan,
    ServiceReceipt,
)
from binnacle.platform.contracts.service_lifecycle_contracts import (
    ManagedServiceStatus,
    ServiceAction,
)
from binnacle.platform.darwin.generation_runtime import (
    lease_root,
    private_file,
    validate_lease,
)
from binnacle.platform.darwin.ipc_transport import connect_authenticated

_SCOPE = "test-owned user launchd registration, leader and socket only; descendants unverified"


def _cap(state: CapabilityState, code: str) -> Capability:
    return Capability(state, code, _SCOPE)


def _unknown(code: str) -> AuthorityUnknown:
    return AuthorityUnknown(code, _cap(CapabilityState.UNKNOWN, code))


def _native() -> None:
    if sys.platform != "darwin":
        raise CapabilityUnavailable(
            "launchd_unavailable",
            _cap(CapabilityState.UNAVAILABLE, "launchd_unavailable"),
        )


def _run(*args: str, timeout_s: float = 5) -> subprocess.CompletedProcess[str]:
    _native()
    try:
        return subprocess.run(
            ["/bin/launchctl", *args],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise _unknown("launchd_command_failed") from exc


def _absent(result: subprocess.CompletedProcess[str]) -> bool:
    # Other print errors (domain inaccessible, permissions, tool failure) are
    # UNKNOWN, never positive evidence of service absence.
    return result.returncode == 113 and "Could not find service" in result.stderr


def _bootout_observed(target: str, pid: int, deadline: float) -> bool:
    # kqueue observes an exit; it grants no numeric PID signal authority.
    if sys.platform == "darwin":
        with closing(select.kqueue()) as queue:
            try:
                queue.control(
                    [
                        select.kevent(
                            pid,
                            filter=select.KQ_FILTER_PROC,
                            flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
                            fflags=select.KQ_NOTE_EXIT,
                        )
                    ],
                    0,
                    0,
                )
            except OSError as exc:
                raise _unknown("launchd_leader_watch_failed") from exc
            result = _run(
                "bootout", target, timeout_s=max(0.001, deadline - time.monotonic())
            )
            if result.returncode:
                raise _unknown("launchd_bootout_failed")
            events = queue.control(None, 1, max(0, deadline - time.monotonic()))
            return any(
                event.ident == pid and event.fflags & select.KQ_NOTE_EXIT
                for event in events
            )
    else:
        raise _unknown("launchd_unavailable")


class LaunchdUserServices:
    def __init__(self, lease: ServiceLease) -> None:
        if lease.uid != os.getuid() or not lease.label.startswith(
            "com.binnacle.r3test."
        ):
            raise _unknown("launchd_label_not_test_owned")
        self.lease = lease
        self.root = lease_root(lease)
        self.target = f"user/{lease.uid}/{lease.label}"
        self._plan: ServicePlan | None = None
        self._digest: str | None = None
        self._role: str | None = None
        self._pid: int | None = None
        self._plist_identity: tuple[int, int] | None = None

    def _validate(self, lease: ServiceLease) -> None:
        if lease != self.lease:
            raise _unknown("launchd_lease_mismatch")
        fd = validate_lease(self.root, lease)
        os.close(fd)

    def _read_plan(self, plan: ServicePlan) -> bytes:
        self._validate(plan.lease)
        if plan.plist_path.parent != self.root:
            raise _unknown("launchd_plist_outside_root")
        fd = validate_lease(self.root, plan.lease)
        try:
            file_fd = private_file(fd, plan.plist_path.name)
            try:
                info = os.fstat(file_fd)
                identity = (info.st_dev, info.st_ino)
                if (
                    self._plist_identity is not None
                    and identity != self._plist_identity
                ):
                    raise _unknown("launchd_plist_identity_changed")
                self._plist_identity = identity
                return os.read(file_fd, 65537)
            finally:
                os.close(file_fd)
        finally:
            os.close(fd)

    def bootstrap(self, plan: ServicePlan) -> ServiceReceipt:
        self._validate(plan.lease)
        if self._plan is not None or plan.expected_previous_sha256 is not None:
            raise _unknown("launchd_adoption_refused")
        if self._read_plan(plan) != plan.plist_bytes:
            raise _unknown("launchd_plan_changed")
        try:
            value = plistlib.loads(plan.plist_bytes)
        except (ValueError, plistlib.InvalidFileException) as exc:
            raise _unknown("launchd_plist_invalid") from exc
        self._validate_plist(value)
        before = _run("print", self.target)
        if not _absent(before):
            raise _unknown("launchd_registration_not_absent")
        result = _run("bootstrap", f"user/{self.lease.uid}", str(plan.plist_path))
        if result.returncode:
            # A failing bootstrap does not grant permission to boot out a label.
            raise _unknown("launchd_bootstrap_failed")
        self._plan = plan
        self._digest = hashlib.sha256(plan.plist_bytes).hexdigest()
        self._role = value["EnvironmentVariables"]["BINNACLE_SERVICE_ROLE"]
        status = self.status(self.lease.label)
        self._pid = status.main_pid
        return ServiceReceipt(
            self.lease,
            "bootstrap",
            _cap(CapabilityState.LIMITED, "launchd_registered_not_ready"),
            False,
        )

    def _validate_plist(self, value: object) -> None:
        if not isinstance(value, dict):
            raise _unknown("launchd_plist_invalid")
        env = value.get("EnvironmentVariables", {})
        argv = value.get("ProgramArguments")
        if (
            value.get("Label") != self.lease.label
            or not isinstance(env, dict)
            or env.get("BINNACLE_SERVICE_ROLE") not in ("frontend", "probe", "manager")
            or env.get("BINNACLE_RUNTIME_DIR") != str(self.root)
            or not isinstance(argv, list)
            or not argv
            or not all(isinstance(arg, str) for arg in argv)
            or not Path(argv[0]).is_absolute()
            or value.get("KeepAlive", False) is not False
            or value.get("LimitLoadToSessionType") != "Background"
            or "Program" in value
            or "UserName" in value
            or "GroupName" in value
            or "Sockets" in value
            or "MachServices" in value
        ):
            raise _unknown("launchd_plist_scope_refused")

    def _owned(self, lease: ServiceLease) -> ServicePlan:
        self._validate(lease)
        if self._plan is None:
            raise _unknown("launchd_registration_not_owned")
        if hashlib.sha256(self._read_plan(self._plan)).hexdigest() != self._digest:
            raise _unknown("launchd_owned_plan_changed")
        current = _run("print", self.target)
        if (
            current.returncode
            or re.search(
                r"^\tpath = " + re.escape(str(self._plan.plist_path)) + r"$",
                current.stdout,
                re.MULTILINE,
            )
            is None
        ):
            raise _unknown("launchd_registration_changed")
        return self._plan

    def readiness(self, lease: ServiceLease, *, timeout_s: float) -> Capability:
        self._validate(lease)
        try:
            channel = connect_authenticated(
                self.root / "jobs.sock", lease=lease, timeout_s=timeout_s
            )
            channel.close()
        except NativeCapabilityError:
            return _cap(CapabilityState.UNKNOWN, "launchd_authenticated_ping_failed")
        return _cap(CapabilityState.LIMITED, "launchd_authenticated_generation_ready")

    def bootout(self, lease: ServiceLease, *, timeout_s: float) -> ServiceReceipt:
        self._owned(lease)
        if self._role not in ("frontend", "probe"):
            raise _unknown("launchd_durable_quiet_gate_unavailable")
        if not 0 < timeout_s <= 60:
            raise _unknown("launchd_timeout_invalid")
        deadline = time.monotonic() + timeout_s
        status = self.status(lease.label)
        pid = status.main_pid
        if pid is None or self._pid not in (None, pid):
            raise _unknown("launchd_leader_unverified")
        self._owned(lease)
        exited = _bootout_observed(self.target, pid, deadline)
        absent = False
        while time.monotonic() < deadline:
            self._validate(lease)
            printed = _run(
                "print", self.target, timeout_s=max(0.001, deadline - time.monotonic())
            )
            socket_absent = not os.path.lexists(self.root / "jobs.sock")
            key_absent = not os.path.lexists(self.root / "jobs.sock.auth")
            if _absent(printed) and exited and socket_absent and key_absent:
                absent = True
                break
            time.sleep(min(0.02, max(0, deadline - time.monotonic())))
        if absent:
            self._plan = None
        return ServiceReceipt(
            lease,
            "bootout",
            _cap(
                CapabilityState.LIMITED if absent else CapabilityState.UNKNOWN,
                "launchd_owned_absent" if absent else "launchd_teardown_unverified",
            ),
            absent,
        )

    def status(self, service: str) -> ManagedServiceStatus:
        if service != self.lease.label:
            return ManagedServiceStatus("unknown")
        self._validate(self.lease)
        result = _run("print", self.target)
        if _absent(result):
            return ManagedServiceStatus("inactive")
        if result.returncode:
            return ManagedServiceStatus("unknown")
        # Only top-level facts; do not infer PID/environment from nested blocks.
        pid_match = re.search(r"^\tpid = ([1-9][0-9]*)$", result.stdout, re.MULTILINE)
        state_match = re.search(
            r"^\tstate = (running|not running)$", result.stdout, re.MULTILINE
        )
        if state_match is None:
            return ManagedServiceStatus("unknown")
        return ManagedServiceStatus(
            "active" if state_match[1] == "running" else "inactive",
            int(pid_match[1]) if pid_match else None,
        )

    def started_at_epoch(self, service: str) -> float | None:
        return None

    def rss_kb(self, service: str) -> float | None:
        return None

    def main_process_has_environment(
        self, service: str, name: str, value: str
    ) -> bool | None:
        return None

    def main_process_path(self, service: str) -> str | None:
        return None

    def restart(self, service: str, *, timeout: float | None = None) -> ServiceAction:
        if (
            service != self.lease.label
            or self._role != "frontend"
            or self._plan is None
        ):
            return ServiceAction(
                1, launch_error="launchd_restart_quiet_gate_unavailable"
            )
        plan = self._plan
        try:
            receipt = self.bootout(
                self.lease, timeout_s=5 if timeout is None else timeout
            )
            if not receipt.absent:
                return ServiceAction(1, launch_error="launchd_teardown_unverified")
            self.bootstrap(plan)
        except NativeCapabilityError as exc:
            return ServiceAction(1, launch_error=exc.code)
        return ServiceAction(0)
