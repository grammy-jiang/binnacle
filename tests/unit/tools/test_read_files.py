"""Implementation gate for the multi-file read core (tools/read_files.py;
docs/tools/read_files.md "Test checklist")."""

import os

import pytest
from fastmcp.exceptions import ToolError

from binnacle.tools import read_file as rf
from binnacle.tools import read_files as rfs


def read(*entries) -> dict:
    payload = rfs.read_files_impl(list(entries)).structured_content
    assert payload is not None
    return payload


def lines(n: int, width: int = 9) -> str:
    return "".join(f"{i:0{width}d}\n" for i in range(1, n + 1))


@pytest.fixture()
def small(tmp_path):
    f = tmp_path / "small.py"
    f.write_text("a = 1\nb = 2\n")
    return f


# -- ordering and shape -------------------------------------------------------


def test_entries_keep_request_order_and_index(tmp_path, small):
    other = tmp_path / "other.md"
    other.write_text("# t\n")
    p = read({"path": str(other)}, {"path": str(small)})
    assert [e["index"] for e in p["files"]] == [0, 1]
    assert [e["path"] for e in p["files"]] == [str(other), str(small)]
    assert p["kind"] == "files" and p["files_requested"] == 2 and p["files_read"] == 2
    assert not p["truncated"] and "next_call" not in p and "note" not in p


def test_one_entry_matches_a_single_read(small):
    single = rf.read_file_impl(str(small), 1, None).structured_content
    entry = read({"path": str(small)})["files"][0]
    assert {k: v for k, v in entry.items() if k != "index"} == single


def test_range_per_entry(tmp_path):
    f = tmp_path / "n.txt"
    f.write_text(lines(50))
    e = read({"path": str(f), "start_line": 10, "end_line": 12})["files"][0]
    assert (e["start_line"], e["end_line"]) == (10, 12)
    assert e["content"] == "000000010\n000000011\n000000012\n"


def test_summary_names_every_outcome(tmp_path, small):
    r = rfs.read_files_impl([{"path": str(small)}, {"path": str(tmp_path / "x")}])
    text = r.content[0].text
    assert text.startswith("Read 1 of 2 files") and "all 2 lines" in text
    assert "error file_not_found" in text


# -- the shared budget ---------------------------------------------------------


def test_small_files_whole_and_large_ones_share_the_rest(tmp_path, monkeypatch):
    monkeypatch.setattr(rfs, "MULTI_BUDGET_CHARS", 30_000)
    tiny = tmp_path / "tiny.txt"
    tiny.write_text(lines(10))  # 100 chars
    big1, big2 = tmp_path / "b1.txt", tmp_path / "b2.txt"
    big1.write_text(lines(2000))  # 20,000 chars each
    big2.write_text(lines(2000))
    p = read({"path": str(big1)}, {"path": str(tiny)}, {"path": str(big2)})
    e_big1, e_tiny, e_big2 = p["files"]
    assert not e_tiny["truncated"] and e_tiny["end_line"] == 10
    assert e_big1["budget_cut"] and e_big2["budget_cut"]
    assert abs(len(e_big1["content"]) - len(e_big2["content"])) <= 10
    assert p["chars"] <= 30_000 and p["truncated"]
    assert p["next_call"]["files"] == [
        {"path": str(big1), "start_line": e_big1["next_start_line"]},
        {"path": str(big2), "start_line": e_big2["next_start_line"]},
    ]
    assert "cut" in p["note"] and "next_call" in p["note"]


def test_next_call_continues_exactly(tmp_path, monkeypatch):
    monkeypatch.setattr(rfs, "MULTI_BUDGET_CHARS", 8_000)
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text(lines(600))
    b.write_text(lines(600))
    first = read({"path": str(a), "end_line": 500}, {"path": str(b)})
    cont = first["next_call"]["files"]
    assert cont[0]["end_line"] == 500  # the requested end survives
    second = read(*cont)
    got_a = first["files"][0]["content"] + second["files"][0]["content"]
    assert got_a == lines(500)


def test_file_limit_cut_is_not_a_budget_cut(tmp_path):
    # One file larger than a single read: same window as read_file, no next_call.
    f = tmp_path / "huge.txt"
    f.write_text(lines(2500))
    e = read({"path": str(f)})["files"][0]
    single = rf.read_file_impl(str(f), 1, None).structured_content
    assert e["truncated"] and e["end_line"] == single["end_line"]
    assert "budget_cut" not in e


def test_budget_too_small_leaves_the_last_files_not_read(tmp_path, monkeypatch):
    monkeypatch.setattr(rfs, "MULTI_BUDGET_CHARS", 10_000)
    names = []
    for i in range(4):
        f = tmp_path / f"f{i}.txt"
        f.write_text(lines(1000))
        names.append(str(f))
    p = read(*({"path": n} for n in names))
    kinds = [e["kind"] for e in p["files"]]
    assert kinds == ["text", "text", "not_read", "not_read"]
    assert all(
        len(e["content"]) >= rfs.MULTI_MIN_SHARE_CHARS - 10
        for e in p["files"]
        if e["kind"] == "text"
    )
    not_read = [e for e in p["files"] if e["kind"] == "not_read"]
    assert all(e["not_read"] and e["request"]["path"] == e["path"] for e in not_read)
    assert p["files_not_read"] == 2 and p["truncated"]
    assert [c["path"] for c in p["next_call"]["files"][-2:]] == names[2:]


# -- per-file problems never fail the call ------------------------------------


@pytest.mark.parametrize(
    ("make", "code"),
    [
        (lambda d: str(d / "missing.txt"), "file_not_found"),
        (lambda d: str(d), "path_is_directory"),
        (lambda d: "/etc/passwd", "path_outside_root"),
    ],
)
def test_path_errors_are_per_entry(tmp_path, small, make, code):
    p = read({"path": make(tmp_path)}, {"path": str(small)})
    bad, good = p["files"]
    assert bad["kind"] == "error" and bad["error"]["code"] == code
    assert bad["error"]["message"] and good["kind"] == "text"
    assert p["files_failed"] == 1 and p["files_read"] == 1 and "failed" in p["note"]


def test_range_errors_are_per_entry(tmp_path, small):
    p = read(
        {"path": str(small), "start_line": 5, "end_line": 2},
        {"path": str(small), "start_line": 99},
    )
    assert [e["error"]["code"] for e in p["files"]] == [
        "range_invalid",
        "range_past_end",
    ]


def test_too_large_is_per_entry(tmp_path, small):
    f = tmp_path / "huge.bin"
    f.write_bytes(b"a")
    with open(f, "r+b") as fh:
        fh.truncate(rf.READ_MAX_FILE_BYTES + 1)
    p = read({"path": str(f)}, {"path": str(small)})
    assert p["files"][0]["error"]["code"] == "file_too_large"


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads unreadable files")
def test_unreadable_file_is_per_entry(tmp_path, small):
    f = tmp_path / "locked.txt"
    f.write_text("secret\n")
    f.chmod(0)
    try:
        p = read({"path": str(f)}, {"path": str(small)})
    finally:
        f.chmod(0o600)
    assert p["files"][0]["error"]["code"] == "read_error"
    assert p["files"][1]["kind"] == "text"


def test_binary_and_empty_entries(tmp_path):
    png, empty = tmp_path / "i.png", tmp_path / "e.txt"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 64)
    empty.write_bytes(b"")
    p = read({"path": str(png)}, {"path": str(empty)})
    assert [e["kind"] for e in p["files"]] == ["binary", "empty"]
    assert p["files_read"] == 2 and p["chars"] == 0


# -- duplicates and limits -----------------------------------------------------


def test_duplicate_is_noted_not_repeated(small):
    p = read(
        {"path": str(small)}, {"path": str(small)}, {"path": str(small), "end_line": 1}
    )
    dup = p["files"][1]
    assert (
        dup["kind"] == "duplicate" and dup["duplicate_of"] == 0 and "content" not in dup
    )
    assert p["files"][2]["kind"] == "text"  # another range is not a duplicate
    assert p["files_duplicate"] == 1 and p["files_read"] == 2


def test_too_many_files_names_the_limit(small):
    with pytest.raises(ToolError, match=f"at most {rfs.MULTI_MAX_FILES} per call"):
        rfs.read_files_impl([{"path": str(small)}] * (rfs.MULTI_MAX_FILES + 1))


def test_empty_list_is_an_error():
    with pytest.raises(ToolError, match="at least one path"):
        rfs.read_files_impl([])


# -- candidate plumbing ---------------------------------------------------------


def test_client_tools_follow_read_file_only_in_tool_mode():
    tools = {"openai-mcp": ("read_file", "run_command"), "other": ("run_command",)}
    assert rfs.effective_client_tools(tools, "off") is tools
    assert rfs.effective_client_tools(tools, "param") is tools
    got = rfs.effective_client_tools(tools, "tool")
    assert got["openai-mcp"] == ("read_file", "run_command", "read_files")
    assert got["other"] == ("run_command",)
    again = rfs.effective_client_tools(got, "tool")
    assert again["openai-mcp"].count("read_files") == 1


def test_descriptions_state_the_limits():
    for text in (rfs.description(), rfs.param_description()):
        assert f"up to {rfs.MULTI_MAX_FILES} entries" in text
        assert f"{rfs.MULTI_BUDGET_CHARS // 1000}k-char budget" in text
        assert "not_read" in text and "next_call" in text
    assert rfs.param_description().startswith(rf.DESCRIPTION)
