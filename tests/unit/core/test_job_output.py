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
