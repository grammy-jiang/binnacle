"""Fixed-vocabulary, bounded synthetic reminder text."""

from dataclasses import replace

from binnacle.features.commands.job_awareness.models import (
    CandidateCategory,
    HintCarrier,
    JobRef,
    ReminderCandidate,
    RenderedHint,
)

MAX_HINT_BYTES = 512
MAX_HINT_JOBS = 2
_WORDS = {
    CandidateCategory.TERMINAL_UNCONFIRMED: "unconfirmed",
    CandidateCategory.TERMINAL_PARTIAL: "partially confirmed",
}


def _within_utf8_budget(message: str) -> bool:
    try:
        return len(message.encode("utf-8")) <= MAX_HINT_BYTES
    except UnicodeError:
        return False


def render_hint(
    candidates: tuple[ReminderCandidate, ...], carrier: HintCarrier
) -> RenderedHint | None:
    """Render only canonical job IDs and fixed receipt state words."""
    if (
        type(carrier) is not HintCarrier
        or type(candidates) is not tuple
        or not 1 <= len(candidates) <= MAX_HINT_JOBS
    ):
        return None
    parts = []
    seen = set()
    for candidate in candidates:
        if type(candidate) is not ReminderCandidate:
            return None
        try:
            if type(candidate.job) is not JobRef:
                return None
            # Validate all fields before hashing, even on an existing frozen value.
            candidate = replace(candidate, job=replace(candidate.job))
        except (AttributeError, ValueError):
            return None
        if candidate.category not in _WORDS:
            return None
        canonical_job = candidate.job
        if canonical_job in seen:
            return None
        seen.add(canonical_job)
        parts.append(f"{canonical_job.canonical_key} {_WORDS[candidate.category]}")
    message = "[Binnacle job reminder] " + "; ".join(parts)
    if not _within_utf8_budget(message):
        return None
    return RenderedHint(carrier, message, len(message.encode("utf-8")))
