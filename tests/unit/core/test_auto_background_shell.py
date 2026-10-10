"""Background command policy ignores shell input/file bodies, not real tools."""

import re

import pytest

from binnacle.auto_background_shell import shell_policy_code
from binnacle.config import AutoBackgroundMatch, RunCommandSettings

RULES = {"openai-mcp": (r"(?i)(?<![\w-])pytest(?![\w-])",)}


def match(script: str) -> AutoBackgroundMatch | None:
    return RunCommandSettings(auto_background_patterns=RULES).match_auto_background(
        "openai-mcp(ChatGPT)", script
    )


def test_source_only_import_no_longer_backgrounds_a_short_edit():
    script = "cat > test_file.py <<'PY'\nimport pytest\nPY\nprintf done\n"
    assert re.search(RULES["openai-mcp"][0], script)
    assert match(script) is None
    assert len(shell_policy_code(script)) == len(script)


def test_original_nighttime_command_still_backgrounds_real_pytest():
    script = (
        "set -e\ncat > tests/integration/cross_version.py <<'PY'\n"
        "import pytest\n\n@pytest.fixture\ndef reusable():\n    pass\nPY\n"
        "uv run ruff check tests/integration/cross_version.py\n"
        "uv run pytest tests/integration/cross_version.py -q\n"
    )
    found = match(script)
    assert found is not None
    assert script[found.match_start : found.match_end] == "pytest"
    assert found.match_start == script.rindex("pytest")
    assert (
        shell_policy_code(script)[
            script.index("import pytest") : script.index("import pytest") + 13
        ].strip()
        == ""
    )


@pytest.mark.parametrize(
    "script",
    [
        "python3 - <<PY\nimport pytest\nPY\necho done\n",
        'cat <<"EOF"\npytest -q\nEOF\necho done\n',
        "cat <<\\EOF\npytest -q\nEOF\necho done\n",
        "cat <<-'EOF'\n\tpytest -q\n\tEOF\necho done\n",
        "cat <<'ONE' <<\"TWO\"\npytest\nONE\npytest\nTWO\necho done\n",
        "# pytest -q\necho done\n",
        "printf done # pytest -q\n",
        "echo 'a <<EOF'\n# pytest\n",
        'echo "a <<EOF"\n# pytest\n',
        "cat <<'PYTEST'\nprint('hello')\nPYTEST\necho done\n",
        "cat <<'PY'\n  pytest\n  PY\npytest -q\n",
    ],
)
def test_noncommand_pytest_tokens_cannot_trigger_auto_background(script):
    # An indented non-<<- delimiter is not a terminator, so the last case
    # stays in the literal here-doc body all the way to EOF.
    assert match(script) is None
    assert len(shell_policy_code(script)) == len(script)


def test_quoted_and_multiple_heredocs_preserve_true_match_positions():
    script = (
        "cat <<\"ONE\" <<'TWO' # pytest in comment\n"
        "import pytest\nONE\npytest -q\nTWO\n"
        "echo safe\n"
        "uv run pytest -q\n"
    )
    result = match(script)
    assert result is not None
    assert result.match_start == script.rindex("pytest")
    assert shell_policy_code(script).count("\n") == script.count("\n")


def test_here_string_is_not_considered_a_heredoc():
    script = "cat <<<'hello'\npytest -q\n"
    assert match(script) is not None


def test_here_string_data_does_not_trigger_a_background_match():
    assert match("cat <<<'pytest'\nprintf done\n") is None
    script = "cat <<<'pytest'\npytest -q\n"
    found = match(script)
    assert found is not None and found.match_start == script.rindex("pytest")


def test_redirection_path_data_is_not_a_command_keyword():
    assert match("printf done > /tmp/pytest-results.log\n") is None
    assert match("cat < '/tmp/pytest-results.log'\n") is None
    assert match("cat > '/tmp/pytest-results.py' <<'PY'\nimport pytest\nPY\n") is None


def test_quoted_executable_arguments_remain_eligible_by_existing_policy():
    # This is intentionally a data-location fix, not a broad behavior change
    # for user-supplied regex rules applied to command-line quoted strings.
    assert match("uv run 'pytest' -q") is not None


def test_no_policy_or_unmatched_client_stays_no_match():
    script = "uv run pytest -q"
    assert RunCommandSettings().match_auto_background("openai-mcp", script) is None
    assert (
        RunCommandSettings(auto_background_patterns=RULES).match_auto_background(
            "unrelated-client", script
        )
        is None
    )


def test_background_semantic_fingerprint_changes_when_lexer_changes():
    from binnacle.features.commands.run_command_telemetry import (
        AUTO_BACKGROUND_SEMANTICS_VERSION,
        auto_background_behavior_hash,
    )

    assert AUTO_BACKGROUND_SEMANTICS_VERSION >= 2
    rules = RULES
    assert auto_background_behavior_hash(
        rules, 1.0, AUTO_BACKGROUND_SEMANTICS_VERSION
    ) != auto_background_behavior_hash(rules, 1.0, 1)


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("'open", None),
        ('"open', None),
        ("", None),
        ('"A\\"B"', 'A"B'),
        ('"A\\q"', "A\\q"),
        (r"\EOF", "EOF"),
        ("'OUT'REST", "OUTREST"),
    ],
)
def test_delimiter_quote_removal_and_malformed_inputs(word, expected):
    from binnacle.auto_background_shell import _delimiter

    delimiter, offset = _delimiter(word, 0)
    assert delimiter == expected
    assert 0 <= offset <= len(word)


@pytest.mark.parametrize(
    "script",
    [
        "cat <<< 'pytest'\nprintf done\n",
        "cat <<<\nprintf done\n",  # deliberately incomplete input
        "cat >\nprintf done\n",  # deliberately incomplete redirection
        "cat <<\nprintf done\n",  # deliberately incomplete heredoc
        "cat << 'PY'\nimport pytest\nPY\nprintf done\n",
        "((x <<= 1)); printf done\n",
        "printf \\#pytest\n",
        "cat 2> '/tmp/pytest-errors.log'\n",
        "cat <<'A\\\"B'\nimport pytest\nA\\\"B\nprintf done\n",
    ],
)
def test_unusual_shell_fragments_do_not_crash_or_change_offsets(script):
    from binnacle.auto_background_shell import shell_policy_code

    code = shell_policy_code(script)
    assert len(code) == len(script)
    assert code.count("\n") == script.count("\n")
    assert shell_policy_code(code) == code


@pytest.mark.parametrize("quoted", ["''", '""'])
def test_codex_p2_empty_quoted_heredoc_terminates_on_blank_line(quoted):
    script = f"cat <<{quoted}\npytest -q\n\nprintf done\n"
    assert match(script) is None
    script += "uv run pytest -q\n"
    found = match(script)
    assert found is not None
    assert found.match_start == script.rindex("pytest")


@pytest.mark.parametrize("quoted", ["$'EOF'", '$"EOF"'])
def test_codex_p2_dollar_quoted_heredoc_removes_quote_prefix(quoted):
    script = f"cat <<{quoted}\npytest -q\nEOF\nprintf done\n"
    assert match(script) is None
    script += "uv run pytest -q\n"
    found = match(script)
    assert found is not None
    assert found.match_start == script.rindex("pytest")


def test_codex_p2_continued_logical_line_still_contains_command():
    script = "cat <<'EOF' \\\n| pytest -q\nexample input data\nEOF\nprintf done\n"
    found = match(script)
    assert found is not None
    assert found.match_start == script.index("pytest")
    masked = shell_policy_code(script)
    assert masked[script.index("example input data") :].startswith(" " * 18)


@pytest.mark.parametrize("redirect", [">|", ">&", "<&", "&>", "&>>"])
def test_codex_p2_compound_redirection_operands_are_data(redirect):
    script = f"printf done {redirect} /tmp/pytest.log\n"
    assert match(script) is None
    script += "uv run pytest -q\n"
    found = match(script)
    assert found is not None
    assert found.match_start == script.rindex("pytest")


@pytest.mark.parametrize(
    ("escaped", "decoded"),
    [
        (r"E\tF", "E\tF"),
        (r"E\nF", "E\nF"),
        (r"E\'F", "E'F"),
        (r"E\"F", 'E"F'),
        (r"E\\F", "E\\F"),
        (r"E\eF", "E\x1bF"),
        (r"E\aF", "E\aF"),
    ],
)
def test_ansi_c_heredoc_delimiter_common_backslash_escapes(escaped, decoded):
    from binnacle.auto_background_shell import _delimiter

    quoted = "$'" + escaped + "'"
    parsed, stop = _delimiter(quoted, 0)
    assert parsed == decoded
    assert stop == len(quoted)


def test_unsupported_ansi_c_escape_is_not_masked_as_an_invented_delimiter():
    from binnacle.auto_background_shell import _delimiter

    parsed, _ = _delimiter(r"$'E\x46'", 0)
    assert parsed is None


@pytest.mark.parametrize(
    "script",
    [
        "echo $(( 1 << 2 ))\nuv run pytest -q\n",
        "(( total = base << shift ))\nuv run pytest -q\n",
        "echo $(( (a << b) + (c << d) ))\nuv run pytest -q\n",
        "((total = base <<\n shift))\nuv run pytest -q\n",
        "cat <<'EOF' $(( 1 << 2 ))\nsource input\nEOF\nuv run pytest -q\n",
    ],
)
def test_copilot_p2_arithmetic_shifts_never_consume_later_commands(script):
    import subprocess

    parsed = subprocess.run(
        ["bash", "-n"], input=script, text=True, capture_output=True, check=False
    )
    assert parsed.returncode == 0, parsed.stderr
    result = match(script)
    assert result is not None
    assert result.match_start == script.rindex("pytest")


def test_arithmetic_variable_named_pytest_is_not_a_command_trigger():
    assert match("echo $((pytest << 2))\nprintf done\n") is None


def test_codex_p2_continued_heredoc_word_joins_before_body():
    script = "cat <<EO\\\nF\nimport pytest\nEOF\nprintf done\n"
    assert match(script) is None
    script += "uv run pytest -q\n"
    found = match(script)
    assert found is not None and found.match_start == script.rindex("pytest")
    assert len(shell_policy_code(script)) == len(script)
    assert shell_policy_code(script).count("\n") == script.count("\n")


def test_codex_p2_continued_heredoc_word_preserves_pipeline():
    script = "cat <<EO\\\nF | pytest -q\ninput text\nEOF\nprintf done\n"
    found = match(script)
    assert found is not None and found.match_start == script.index("pytest")
    assert len(shell_policy_code(script)) == len(script)


@pytest.mark.parametrize("operator", ["|", "||", "&&", "|&"])
def test_codex_p2_operator_continues_heredoc_command(operator):
    import subprocess

    script = f"cat <<'EOF' {operator}\npytest -q\ninput\nEOF\nprintf done\n"
    check = subprocess.run(
        ["bash", "-n"], input=script, text=True, capture_output=True, check=False
    )
    assert check.returncode == 0, check.stderr
    found = match(script)
    assert found is not None and found.match_start == script.index("pytest")
    assert shell_policy_code(script)[script.index("input") :].startswith(" " * 5)


def test_operator_continuation_cannot_confuse_redirect_clobber():
    script = "cat <<'EOF' >| /tmp/pytest.log\npytest -q\nEOF\nuv run pytest -q\n"
    found = match(script)
    assert found is not None and found.match_start == script.rindex("pytest")


def test_two_operator_continuations_while_heredoc_is_pending():
    script = "cat <<'EOF' |\ncat &&\npytest -q\ninput\nEOF\nprintf done\n"
    found = match(script)
    assert found is not None and found.match_start == script.index("pytest")
