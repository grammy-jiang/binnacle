"""Pure receipt projection. Delivery and process exit never confirm a page."""

from binnacle.features.commands.job_awareness.identifiers import bounded_int, require
from binnacle.features.commands.job_awareness.models import (
    MAX_INTEGER,
    PAGE_BYTES,
    ByteRange,
    ConsumerReceipt,
    OutputSnapshot,
    ReceiptState,
)


def canonical_page(snapshot: OutputSnapshot, start: int) -> ByteRange:
    """Validate a fixed page, including the one explicit empty page."""
    require(type(snapshot) is OutputSnapshot)
    bounded_int(start, 0, snapshot.byte_length)
    require(start % PAGE_BYTES == 0)
    require(start < snapshot.byte_length or start == snapshot.byte_length == 0)
    return ByteRange(start, min(start + PAGE_BYTES, snapshot.byte_length))


def project_receipt(
    snapshot: OutputSnapshot,
    starts: tuple[int, ...],
    version: int,
    revision: int,
    now_ms: int,
) -> ConsumerReceipt:
    """Project validated canonical pages; expired history never implies COMPLETE."""
    require(type(starts) is tuple and len(starts) <= 64)
    bounded_int(now_ms, 0, MAX_INTEGER)
    for start in starts:
        canonical_page(snapshot, start)
    pages = tuple(canonical_page(snapshot, start) for start in sorted(set(starts)))
    empty = snapshot.byte_length == 0 and bool(pages)
    if now_ms >= snapshot.retained_until_ms:
        state = ReceiptState.OUTPUT_EXPIRED
    elif not pages:
        state = ReceiptState.UNCONFIRMED
    elif empty or sum(page.stop - page.start for page in pages) == snapshot.byte_length:
        state = ReceiptState.COMPLETE
    else:
        state = ReceiptState.PARTIAL
    return ConsumerReceipt(
        state, snapshot.job, snapshot.sha256, pages, empty, version, revision
    )
