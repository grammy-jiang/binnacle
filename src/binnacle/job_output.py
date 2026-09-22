"""Output shaping shared by the command-job tools."""


def clip_head_tail(text: str, limit: int) -> tuple[str, bool]:
    """Clip a string to a head/tail source-character budget."""
    if len(text) <= limit:
        return text, False
    head = limit // 2
    tail = limit - head
    omitted = len(text) - limit
    # text[len(text) - tail:], not text[-tail:]: with tail == 0 the latter is
    # the whole string (property test, 2026-09-13).
    return (
        f"{text[:head]}\n[… {omitted} chars elided …]\n{text[len(text) - tail :]}",
        True,
    )
