"""Smoke correlation must remain precise after raw arguments are removed."""

from scripts.smoke_diagnostics import missing_from


def test_same_tool_different_smoke_proofs_do_not_mask_missing_results():
    first = "a" * 32
    second = "b" * 32
    lines = [
        f"x INFO: event=tool_call call=a11 tool=run_command smoke={first} "
        + 'args={"command":"[redacted]"}',
        "x INFO: event=tool_result call=a11 tool=run_command is_error=False",
        f"x INFO: event=tool_call call=b22 tool=run_command smoke={second} "
        + 'args={"command":"[redacted]"}',
    ]
    assert missing_from(
        lines,
        [
            ("run_command", (f"smoke={first}",)),
            ("run_command", (f"smoke={second}",)),
        ],
    ) == ["run_command"]


def test_wrong_probe_or_wrong_result_call_never_satisfies_expected_proof():
    expected = "c" * 32
    other = "d" * 32
    lines = [
        f"x INFO: event=tool_call call=a11 tool=read_file smoke={other}",
        "x INFO: event=tool_result call=a11 tool=read_file is_error=False",
        f"x INFO: event=tool_call call=b22 tool=read_file smoke={expected}",
        "x INFO: event=tool_result call=c33 tool=read_file is_error=False",
    ]
    assert missing_from(lines, [("read_file", (f"smoke={expected}",))]) == ["read_file"]


def test_complete_probe_pair_is_accepted_without_raw_nonce():
    proof = "e" * 32
    lines = [
        f"x INFO: event=tool_call call=a11 tool=read_file smoke={proof} "
        + 'args={"path":"pathhash:aabbccddeeff.file"}',
        "x INFO: event=tool_result call=a11 tool=read_file is_error=False",
    ]
    assert missing_from(lines, [("read_file", (f"smoke={proof}",))]) == []
