"""Additional Bash continuation and heredoc masking regression scenarios."""

import pytest

from binnacle.auto_background_shell import shell_policy_code
from binnacle.config import AutoBackgroundMatch, RunCommandSettings

RULES = {"openai-mcp": (r"(?i)(?<![\\w-])pytest(?![\\w-])",)}


def match(script: str) -> AutoBackgroundMatch | None:
    return RunCommandSettings(auto_background_patterns=RULES).match_auto_background(
        "openai-mcp(ChatGPT)", script
    )


@pytest.mark.parametrize("suffix", ["\\|", "\\&\\&", "\\|\\|"])
def test_codex_p2_escaped_operator_is_literal_heredoc_command_argument(suffix):
    import subprocess

    script = f"printf done <<EOF {suffix}\npytest -q\nEOF\n"
    syntax = subprocess.run(
        ["bash", "-n"], input=script, text=True, capture_output=True, check=False
    )
    assert syntax.returncode == 0, syntax.stderr
    assert match(script) is None
    script += "uv run pytest -q\n"
    found = match(script)
    assert found is not None and found.match_start == script.rindex("pytest")


def test_double_backslash_followed_by_real_pipe_continues_pipeline():
    import subprocess

    script = "cat <<EOF \\\\ |\npytest -q\ninput\nEOF\nprintf done\n"
    syntax = subprocess.run(
        ["bash", "-n"], input=script, text=True, capture_output=True, check=False
    )
    assert syntax.returncode == 0, syntax.stderr
    found = match(script)
    assert found is not None and found.match_start == script.index("pytest")


def test_codex_p2_comment_after_physical_line_join_is_still_a_comment():
    import subprocess

    slash = chr(92)
    script = f"printf done {slash}\n# <<EOF\nuv run pytest -q\n"
    syntax = subprocess.run(
        ["bash", "-n"], input=script, text=True, capture_output=True, check=False
    )
    assert syntax.returncode == 0, syntax.stderr
    found = match(script)
    assert found is not None and found.match_start == script.rfind("pytest")


@pytest.mark.parametrize(
    "skipped_lines", ["# explanation\n", "\n", "# comment\n\n# more\n"]
)
def test_codex_p2_pipeline_continuation_survives_comments_and_blank_lines(
    skipped_lines,
):
    import subprocess

    script = f"cat <<'EOF' |\n{skipped_lines}pytest -q\ninput\nEOF\nprintf done\n"
    syntax = subprocess.run(
        ["bash", "-n"], input=script, text=True, capture_output=True, check=False
    )
    assert syntax.returncode == 0, syntax.stderr
    found = match(script)
    assert found is not None and found.match_start == script.index("pytest")


def test_codex_p2_unquoted_heredoc_terminator_joins_physical_lines():
    import subprocess

    slash = chr(92)
    script = f"cat <<EOF\nEO{slash}\nF\nuv run pytest -q\n"
    syntax = subprocess.run(
        ["bash", "-n"], input=script, text=True, capture_output=True, check=False
    )
    assert syntax.returncode == 0, syntax.stderr
    found = match(script)
    assert found is not None and found.match_start == script.rfind("pytest")


def test_quoted_heredoc_terminator_must_not_join_physical_lines():
    slash = chr(92)
    script = f"cat <<'EOF'\nEO{slash}\nF\nuv run pytest -q\n"
    assert match(script) is None


def test_joined_unquoted_terminator_really_ends_heredoc_in_bash():
    import subprocess

    slash = chr(92)
    script = f"cat <<EOF\nEO{slash}\nF\necho after\n"
    # The terminator is EOF after removing escaped physical newline. If it
    # were not a terminator, Bash would swallow the following printf.
    check = subprocess.run(
        ["bash", "-c", script], text=True, capture_output=True, check=False
    )
    assert check.returncode == 0, check.stderr
    assert check.stdout == "after\n"


def test_escaped_newline_does_not_make_hash_comment_inside_shell_word():
    import subprocess

    slash = chr(92)
    script = f"printf done{slash}\n# <<EOF\npytest -q\nEOF\n"
    syntax = subprocess.run(
        ["bash", "-n"], input=script, text=True, capture_output=True, check=False
    )
    assert syntax.returncode == 0, syntax.stderr
    # Bash reads pytest as heredoc body because the joined word is done#.
    assert match(script) is None


def test_unquoted_here_doc_terminator_supports_multiple_joined_lines():
    slash = chr(92)
    script = f"cat <<EOF\nE{slash}\nO{slash}\nF\nuv run pytest -q\n"
    found = match(script)
    assert found is not None and found.match_start == script.rfind("pytest")
    masked = shell_policy_code(script)
    assert len(masked) == len(script)
    assert masked.count("\n") == script.count("\n")


def test_tab_stripped_heredoc_terminator_can_be_joined():
    slash = chr(92)
    script = f"cat <<-EOF\n\tEO{slash}\nF\nuv run pytest -q\n"
    found = match(script)
    assert found is not None and found.match_start == script.rfind("pytest")
