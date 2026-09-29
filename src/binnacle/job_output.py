"""Output shaping shared by the command-job tools."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RunCommandOutputShape:
    output: str
    truncated: bool
    dropped_lines: int
    char_clipped: bool
    selected_chars: int
    returned_chars: int
    omitted_chars: int

    @property
    def reason(self) -> str | None:
        if self.dropped_lines and self.char_clipped:
            return "tail_lines+char_limit"
        if self.dropped_lines:
            return "tail_lines"
        if self.char_clipped:
            return "char_limit"
        return None


def _elision_marker(omitted: int) -> str:
    return f"\n[… {omitted} chars elided …]\n"


def _clip_head_tail_details(text: str, limit: int) -> tuple[str, bool, int]:
    if len(text) <= limit:
        return text, False, 0
    head = limit // 2
    tail = limit - head
    omitted = len(text) - limit
    return (
        f"{text[:head]}{_elision_marker(omitted)}{text[len(text) - tail :]}",
        True,
        omitted,
    )


def clip_head_tail_hard(text: str, limit: int) -> tuple[str, bool, int]:
    """Clip head+tail to a hard returned-character budget, marker included."""
    if len(text) <= limit:
        return text, False, 0
    if limit <= 0:
        return "", True, len(text)

    # Reuse the existing elision vocabulary, but count the marker itself inside
    # the hard budget. Recompute if the omitted-count digit width changes.
    retained = max(0, limit - len(_elision_marker(len(text))))
    while True:
        omitted = len(text) - retained
        marker = _elision_marker(omitted)
        next_retained = max(0, limit - len(marker))
        if next_retained == retained:
            break
        retained = next_retained

    if len(marker) > limit:
        # Pathological tiny configured budgets cannot fit the marker. Keep the
        # hard ceiling and preserve both ends rather than exceeding the budget.
        head = limit // 2
        tail = limit - head
        output = text[:head] + (text[len(text) - tail :] if tail else "")
        return output, True, len(text) - limit

    head = retained // 2
    tail = retained - head
    output = text[:head] + marker + (text[len(text) - tail :] if tail else "")
    return output, True, omitted


def clip_head_tail(text: str, limit: int) -> tuple[str, bool]:
    """Clip a string to a head/tail source-character budget."""
    output, clipped, _ = _clip_head_tail_details(text, limit)
    return output, clipped


def shape_run_command_output(
    text: str, limit: int, tail_lines: int | None = None
) -> RunCommandOutputShape:
    """Apply run_command's historical line selection then char clipping."""

    selected = text
    dropped_lines = 0
    if tail_lines is not None:
        lines = text.splitlines(keepends=True)
        if len(lines) > tail_lines:
            dropped_lines = len(lines) - tail_lines
            selected = "".join(lines[-tail_lines:])

    output, char_clipped, omitted_chars = _clip_head_tail_details(selected, limit)
    if dropped_lines:
        output = (
            f"[… {dropped_lines} earlier lines omitted (tail_lines={tail_lines}) …]\n"
            + output
        )

    return RunCommandOutputShape(
        output=output,
        truncated=bool(dropped_lines or char_clipped),
        dropped_lines=dropped_lines,
        char_clipped=char_clipped,
        selected_chars=len(selected),
        returned_chars=len(output),
        omitted_chars=omitted_chars,
    )
