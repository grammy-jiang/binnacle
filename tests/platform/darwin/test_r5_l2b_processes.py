"""r5 L2b: Darwin job_status processes[] items take the Linux shape (SD-59).

Linux ``job_processes`` yields ``{pid, state, etime_s, cpu_s, cmd}``. The
Darwin manager's ``group_listing`` drops ``ppid``, derives ``etime_s`` from
kinfo_proc p_starttime and emits a state letter only where p_stat alone fixes
it. ``cpu_s`` has no public per-process source and the Linux outputSchema does
not allow null, so it stays absent until the Supervisor rules again. The
kinfo_proc records here are synthetic, so the module runs on every host.
"""

import struct
import time
from pathlib import Path

import jsonschema  # type: ignore[import-untyped]
import pytest

from binnacle.features.commands.tools import job_status as js
from binnacle.platform.darwin import job_manager_entry as entry

LINUX_KEYS = ["pid", "state", "etime_s", "cpu_s", "cmd"]
NOW = 1_800_000_000.0


def kinfo(pid, *, pgid=500, stat=2, flag=0, started=(1_799_999_990, 0), comm=b""):
    """One LP64 kinfo_proc (SDK offsets: p_starttime 0, p_flag 32, p_stat 36,
    p_pid 40, p_comm 243, e_ppid 560, e_pgid 564)."""
    raw = bytearray(648)
    struct.pack_into("=qi", raw, 0, *started)
    struct.pack_into("=i", raw, 32, flag)
    raw[36] = stat
    struct.pack_into("=i", raw, 40, pid)
    raw[243 : 243 + len(comm)] = comm
    struct.pack_into("=ii", raw, 560, 1, pgid)
    return bytes(raw)


@pytest.fixture
def listing(monkeypatch):
    """group_listing over synthetic records; argv by pid, None = denied."""

    def run(records, argv=None, max_cmd_chars=200):
        argv = argv or {}
        monkeypatch.setattr(entry, "_sysctl", lambda mib, limit: b"".join(records))
        monkeypatch.setattr(
            entry, "command_line", lambda pid, n: argv.get(pid) and argv[pid][:n]
        )
        monkeypatch.setattr(time, "time", lambda: NOW)
        return entry.group_listing(500, max_cmd_chars)

    return run


@pytest.mark.parametrize(
    ("stat", "flag", "letter"),
    [
        (1, 0, "?"),  # SIDL: no Linux state
        (2, 0, "?"),  # SRUN: running or sleeping, needs libproc thread states
        (3, 0, "S"),  # SSLEEP
        (4, 0, "T"),  # SSTOP
        (4, 0x800, "?"),  # traced SSTOP may be Linux "t"
        (5, 0, "Z"),  # SZOMB
    ],
)
def test_state_letter_only_where_p_stat_decides(stat, flag, letter):
    assert entry._state_letter(kinfo(7, stat=stat, flag=flag), stat) == letter


def test_items_take_the_linux_key_order_without_ppid(listing):
    items = listing(
        [
            kinfo(902, stat=5, started=(1_799_999_999, 960_000), comm=b"sleep"),
            kinfo(901, started=(1_799_999_987, 449_000)),
            kinfo(903, pgid=777),  # another group: never listed
        ],
        argv={901: "bash -c for i in 1 2; do sleep 1; done"},
    )
    assert items == [
        {
            "pid": 901,
            "state": "?",
            "etime_s": 12.6,
            "cmd": "bash -c for i in 1 2; do sleep 1; done",
        },
        {"pid": 902, "state": "Z", "etime_s": 0.0, "cmd": "sleep"},
    ]
    # Linux order minus cpu_s, which is pending (no null in the outputSchema).
    assert all(list(item) == [k for k in LINUX_KEYS if k != "cpu_s"] for item in items)


def test_cmd_is_bounded_and_empty_when_kinfo_has_no_comm(listing):
    (bounded,) = listing([kinfo(11)], argv={11: "sleep 30"}, max_cmd_chars=5)
    assert bounded["cmd"] == "sleep"
    (comm,) = listing([kinfo(12, comm=b"python3.13")], max_cmd_chars=6)
    assert comm["cmd"] == "python"  # comm fallback, bounded
    (empty,) = listing([kinfo(13)])
    assert empty["cmd"] == ""  # like an empty Linux cmdline, never invented


def test_future_start_never_gives_negative_etime(listing):
    (item,) = listing([kinfo(14, started=(1_800_000_005, 0))])
    assert item["etime_s"] == 0.0


def test_items_validate_against_the_linux_job_status_schema(listing):
    items = listing([kinfo(21, stat=3), kinfo(22)], argv={21: "sleep 1"})
    schema = js.OUTPUT_SCHEMA["properties"]["processes"]
    assert list(schema["items"]["properties"]) == LINUX_KEYS
    assert schema["items"]["properties"]["cpu_s"] == {"type": "number"}  # no null
    jsonschema.validate(items, schema)
    closed = {**schema["items"], "additionalProperties": False}
    for item in items:
        jsonschema.validate(item, closed)  # no key outside the Linux set


def test_listing_keeps_the_libproc_ban():
    source = Path(entry.__file__).read_text()
    assert "proc_pidinfo" not in source and "libproc.dylib" not in source
    assert "/usr/lib/libSystem.B.dylib" in source  # public sysctl(3) only


def test_denied_sysctl_lists_nothing(monkeypatch):
    def denied(mib, limit):
        raise OSError("sysctl read failed")

    monkeypatch.setattr(entry, "_sysctl", denied)
    assert entry.group_listing(500, 200) == []
