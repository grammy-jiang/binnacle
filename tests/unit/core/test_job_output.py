from binnacle import job_output


def test_shape_noop_and_tail_noop():
    plain = job_output.shape_run_command_output("a\nb\n", 100, None)
    assert plain.output == "a\nb\n"
    assert plain.truncated is False and plain.reason is None

    tailed = job_output.shape_run_command_output("a\nb\n", 100, 10)
    assert tailed == plain


def test_shape_tail_only_preserves_historical_marker():
    result = job_output.shape_run_command_output("1\n2\n3\n4\n", 100, 2)
    assert result.output == "[… 2 earlier lines omitted (tail_lines=2) …]\n3\n4\n"
    assert result.truncated is True
    assert result.reason == "tail_lines"
    assert result.dropped_lines == 2
    assert result.char_clipped is False
    assert result.selected_chars == 4
    assert result.omitted_chars == 0


def test_shape_char_limit_only_matches_clip_contract():
    result = job_output.shape_run_command_output("abcdefghij", 6)
    old, clipped = job_output.clip_head_tail("abcdefghij", 6)
    assert result.output == old and clipped is True
    assert result.reason == "char_limit"
    assert result.dropped_lines == 0
    assert result.char_clipped is True
    assert result.omitted_chars == 4


def test_shape_tail_and_char_limit_combines_reasons():
    result = job_output.shape_run_command_output("aaaa\nbbbb\ncccc\ndddd\n", 8, 3)
    assert result.reason == "tail_lines+char_limit"
    assert result.dropped_lines == 1
    assert result.char_clipped is True
    assert result.omitted_chars == len("bbbb\ncccc\ndddd\n") - 8


def test_shape_empty_and_non_ascii_count_source_characters():
    empty = job_output.shape_run_command_output("", 0)
    assert empty.output == "" and empty.truncated is False
    unicode_result = job_output.shape_run_command_output("猫猫猫猫", 2)
    assert unicode_result.char_clipped is True
    assert unicode_result.omitted_chars == 2


def test_hard_clip_counts_elision_marker_inside_returned_budget():
    text = "HEAD-" + "x" * 200_000 + "-TAIL"
    output, clipped, omitted = job_output.clip_head_tail_hard(text, 24_000)

    assert clipped is True
    assert len(output) == 24_000
    assert output.startswith("HEAD-")
    assert output.endswith("-TAIL")
    assert f"[… {omitted} chars elided …]" in output
    assert omitted == len(text) - (24_000 - len(job_output._elision_marker(omitted)))


def test_hard_clip_is_noop_below_budget():
    assert job_output.clip_head_tail_hard("small", 24_000) == ("small", False, 0)


def test_consume_utf8_ascii_and_empty():
    assert job_output.consume_utf8(b"plain", at_eof=False, final=False) == (
        "plain",
        5,
    )
    assert job_output.consume_utf8(b"", at_eof=True, final=False) == ("", 0)
    assert job_output.consume_utf8(b"", at_eof=True, final=True) == ("", 0)


def test_consume_utf8_split_multibyte_mid_chunk_backs_off():
    for char in ("¢", "猫", "😀"):
        encoded = char.encode()
        for cut in range(1, len(encoded)):
            data = b"A" + encoded[:cut]
            assert job_output.consume_utf8(data, at_eof=False, final=False) == ("A", 1)


def test_consume_utf8_split_multibyte_eof_running_stays_pending():
    for char in ("¢", "猫", "😀"):
        encoded = char.encode()
        for cut in range(1, len(encoded)):
            data = b"A" + encoded[:cut]
            assert job_output.consume_utf8(data, at_eof=True, final=False) == ("A", 1)


def test_consume_utf8_split_multibyte_terminal_flushes_replacement():
    for char in ("¢", "猫", "😀"):
        encoded = char.encode()
        for cut in range(1, len(encoded)):
            data = b"A" + encoded[:cut]
            assert job_output.consume_utf8(data, at_eof=True, final=True) == (
                "A�",
                len(data),
            )


def test_consume_utf8_terminal_mid_chunk_still_backs_off():
    data = b"A" + "😀".encode()[:2]

    assert job_output.consume_utf8(data, at_eof=False, final=True) == ("A", 1)


def test_consume_utf8_invalid_bytes_are_replaced_and_consumed():
    data = b"A" + bytes([0xFF]) + b"B" + bytes([0x80]) + b"C"
    assert job_output.consume_utf8(data, at_eof=False, final=False) == (
        "A�B�C",
        len(data),
    )


def test_consume_utf8_four_byte_chunk_consumes_complete_character():
    data = "猫".encode() + bytes([0xF0])
    text, consumed = job_output.consume_utf8(data, at_eof=False, final=False)

    assert text == "猫"
    assert consumed == 3
