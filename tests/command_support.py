"""An explicit in-memory command backend for use-case and native adapter tests."""

from binnacle.features.commands.job_store import JobGone


class MemoryCommands:
    owner_mode = "test-owner"
    warmup_s = 0.125
    max_output_chars = 100

    def __init__(self, job_id="fixed"):
        self.job_id = job_id
        self.calls = []
        self.output = b"ready\n"
        self.state = {
            "job_id": job_id,
            "state": "running",
            "exit_code": None,
            "signal": None,
            "runtime_s": 3.0,
            "last_output_age_s": 2.0,
            "started_at": 1.0,
            "pgid": 42,
            "log_bytes": 6,
            "log_path": "/fake/out.log",
            "command": "probe",
            "workdir": "/tmp",
        }
        self.rows = [self.state]

    def __bool__(self):
        return False  # Supplied backends must be selected by identity with None.

    def __deepcopy__(self, memo):
        raise AssertionError("a backend is shared, never copied")

    def start_and_wait(self, *args):
        self.calls.append(("start", args))
        return self.job_id

    def job_state(self, job_id):
        self.calls.append(("state", job_id))
        return self.state

    def read_log(self, job_id):
        self.calls.append(("log", job_id))
        return self.output

    def list_jobs(self):
        self.calls.append(("list",))
        return self.rows

    def await_exit(self, job_id, timeout):
        self.calls.append(("wait", job_id, timeout))
        return self.state

    def read_log_range(self, job_id, start, max_bytes):
        self.calls.append(("range", job_id, start, max_bytes))
        if self.state is None:
            raise JobGone(job_id)
        return self.output[start : start + max_bytes], len(self.output)

    def job_processes(self, pgid, max_cmd_chars=200):
        self.calls.append(("processes", pgid, max_cmd_chars))
        return [{"pid": pgid, "state": "S", "etime_s": 3, "cpu_s": 0, "cmd": "probe"}]

    def stop_job(self, job_id):
        self.calls.append(("stop", job_id))
        if self.state is not None:
            self.state = {**self.state, "state": "exited", "signal": 15}
        return self.state
