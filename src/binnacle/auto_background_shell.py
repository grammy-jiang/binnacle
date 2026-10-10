"""Conservative shell-source mask for deployment-local background matching.

Binnacle executes the original script with bash. Regex policy matching must not
mistake a here-document's *data* for another command; mask data without
changing original character offsets used in audit records.

This is deliberately not a general shell parser. Unsupported/nested shell
syntax may still require an explicit ``background`` choice by the caller.
"""

from collections import deque


def _blank(text: str) -> str:
    """Keep character positions, including line terminators, unchanged."""
    return "".join(ch if ch in "\r\n" else " " for ch in text)


def _delimiter(line: str, start: int) -> tuple[str | None, int]:
    """Read the literal here-doc word, performing shell quote removal only."""
    chars: list[str] = []
    quote: str | None = None
    ansi_quote = False
    i = start
    while i < len(line):
        ch = line[i]
        if quote is None:
            if ch in " \t;|&()<>\r\n":
                break
            if ch == "$" and i + 1 < len(line) and line[i + 1] in "\"'":
                i += 1
                quote = line[i]
                ansi_quote = quote == "'"
            elif ch in "\"'":
                quote = ch
                ansi_quote = False
            elif ch == "\\" and i + 1 < len(line):
                i += 1
                # Bash removes escaped physical newlines before parsing
                # here-document delimiter words such as <<EO\\\nF.
                if line[i] not in "\r\n":
                    chars.append(line[i])
                elif line[i] == "\r" and i + 1 < len(line) and line[i + 1] == "\n":
                    i += 1
            else:
                chars.append(ch)
        elif ch == quote:
            quote = None
            ansi_quote = False
        elif ansi_quote and ch == "\\" and i + 1 < len(line):
            # Bash ANSI-C $'...' literals require backslash interpretation.
            # Handle ordinary escapes; for exotic/unknown escapes, decline
            # the masking optimization rather than hide executable code.
            i += 1
            following = line[i]
            translated = {
                "a": "\a",
                "b": "\b",
                "e": "\x1b",
                "E": "\x1b",
                "f": "\f",
                "n": "\n",
                "r": "\r",
                "t": "\t",
                "v": "\v",
                "\\": "\\",
                "'": "'",
                '"': '"',
                "?": "?",
            }.get(following)
            if translated is None:
                return None, i + 1
            chars.append(translated)
        elif quote == '"' and ch == "\\" and i + 1 < len(line):
            # In a double-quoted word the backslash is special for these
            # characters, but otherwise remains part of the delimiter.
            following = line[i + 1]
            if following in "\r\n":
                # Backslash-newline disappears inside double-quoted words,
                # including heredoc delimiter words and CRLF input.
                i += 1
                if following == "\r" and i + 1 < len(line) and line[i + 1] == "\n":
                    i += 1
            elif following in '\\"$`':
                i += 1
                chars.append(following)
            else:
                chars.append(ch)
        else:
            chars.append(ch)
        i += 1
    if quote is not None or i == start:
        return None, i
    return "".join(chars), i


def _code_line(
    line: str, arithmetic_depth: int = 0
) -> tuple[str, list[tuple[str, bool]], int]:
    """Find here-doc declarations outside quotes/comments/arithmetic."""
    visible = list(line)
    here_docs: list[tuple[str, bool]] = []
    quote: str | None = None
    i = 0
    while i < len(line):
        ch = line[i]
        if arithmetic_depth:
            # `<<` inside `((expr))` or `$((expr))` is shift, not a
            # heredoc declaration. Track ordinary nested parentheses and
            # preserve this context across physical newline boundaries.
            visible[i] = ch if ch in "\r\n" else " "
            if ch == "(":
                arithmetic_depth += 1
            elif ch == ")":
                arithmetic_depth -= 1
            i += 1
            continue
        if ch == "\\" and quote != "'":
            i += 2
            continue
        if quote is not None:
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'":
            quote = ch
            i += 1
            continue
        if line.startswith("$((", i) or line.startswith("((", i):
            width = 3 if line.startswith("$((", i) else 2
            visible[i : i + width] = " " * width
            arithmetic_depth = 2
            i += width
            continue
        if ch == "#" and (i == 0 or line[i - 1] in " \t;|&(){}"):
            visible[i:] = _blank(line[i:])
            break
        if line[i : i + 3] == "<<<":
            # Here-string words feed stdin, not the executable command.
            j = i + 3
            while j < len(line) and line[j] in " \t":
                j += 1
            _, end = _delimiter(line, j)
            if end > j:
                visible[j:end] = " " * (end - j)
            i = max(end, i + 3)
            continue
        if line[i : i + 2] != "<<":
            if (ch in "<>" or line[i : i + 2] == "&>") and (
                i + 1 >= len(line) or line[i + 1] != "("
            ):
                # Path literals redirected into/out of a command are data,
                # not a command name. This also covers quoted tmp paths.
                compound = ("&>>", ">>", "<>", ">|", ">&", "<&", "&>")
                j = i + next(
                    (
                        len(operator)
                        for operator in compound
                        if line.startswith(operator, i)
                    ),
                    1,
                )
                while j < len(line) and line[j] in " \t":
                    j += 1
                _, end = _delimiter(line, j)
                if end > j:
                    visible[j:end] = " " * (end - j)
                    i = end
                    continue
            i += 1
            continue
        j = i + 2
        if j < len(line) and line[j] == "=":
            i += 2  # arithmetic shift assignment is not a here-doc
            continue
        strip_tabs = j < len(line) and line[j] == "-"
        if strip_tabs:
            j += 1
        while j < len(line) and line[j] in " \t":
            j += 1
        delimiter, end = _delimiter(line, j)
        if delimiter is None:
            i += 2
            continue
        here_docs.append((delimiter, strip_tabs))
        visible[i:end] = list(_blank(line[i:end]))
        i = end
    return "".join(visible), here_docs, arithmetic_depth


def _physical_line_continues(line: str) -> bool:
    """Detect shell-active backslash-newline, not comment or single-quote data.

    Run this only for a physical line ending with a backslash. Bash first
    recognizes quotes and comments; a backslash within either a comment or
    single quotes does not join the following line.
    """
    if not line.endswith("\n"):
        return False
    source = line.rstrip("\r\n")
    if (len(source) - len(source.rstrip("\\"))) % 2 != 1:
        return False
    quote: str | None = None
    i = 0
    while i < len(source) - 1:
        ch = source[i]
        if ch == "\\" and quote != "'":
            i += 2
            continue
        if quote is not None:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or source[i - 1] in " \t;|&(){}"):
            return False
        i += 1
    return quote != "'"


def shell_policy_code(script: str) -> str:
    """Hide here-document bodies, delimiters and comments from regex rules.

    Bash consumes here-document bodies in declaration order. They are data,
    even if they contain the names of long-running tools such as pytest.
    A truly executed test command *after* a here-doc remains matchable.
    """
    pending: deque[tuple[str, bool]] = deque()
    result: list[str] = []
    arithmetic_depth = 0
    operator_continued = False
    lines = script.splitlines(keepends=True)
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if pending and not (arithmetic_depth or operator_continued):
            delimiter, strip_tabs = pending[0]
            content = line.rstrip("\r\n")
            if (content.lstrip("\t") if strip_tabs else content) == delimiter:
                pending.popleft()
            result.append(_blank(line))
            operator_continued = False
            continue

        # A backslash-newline joins two physical lines into one logical shell
        # command *before* heredoc words and bodies are interpreted. Preserve
        # every original character, so regex evidence offsets remain stable.
        logical_line = line
        while index < len(lines):
            if not _physical_line_continues(line):
                break
            line = lines[index]
            logical_line += line
            index += 1
        visible, declarations, arithmetic_depth = _code_line(
            logical_line, arithmetic_depth
        )
        result.append(visible)
        pending.extend(declarations)
        # Bash also continues a logical pipeline / AND-OR list after
        # trailing `|`, `|&`, `&&`, or `||`, without needing a backslash.
        # `>|` is a redirection, *not* a pipeline continuation.
        trimmed = visible.rstrip(" \t\r\n")
        operator_continued = trimmed.endswith(("|&", "&&", "||")) or (
            trimmed.endswith("|") and not trimmed.endswith(">|")
        )
    return "".join(result)
