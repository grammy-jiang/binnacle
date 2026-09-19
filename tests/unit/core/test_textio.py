"""Exact-value tests for textio, written against surviving mutants.

The first mutation run on textio (2026-09-13, `mutmut run '*textio*'`) left
24 survivors. Seven are equivalent (codec names are case-insensitive and
`utf-8` is bytes.decode's default); the rest were real gaps: the BOM-plus-
undecodable-body branch had no test, and the property test for
`human_size` only asserted the unit, so `n / 1025` and `>` for `>=` at the
boundaries passed. Each test names the mutants it kills.
"""

from pathlib import Path

from binnacle import textio

NO_EXT = Path("/tmp/no-extension")


# -- decode_text: BOM present but the body does not decode -------------------
# kills x_decode_text__mutmut_8..14 (errors= handling and the lossy flag)


def test_bom_with_undecodable_body_is_replaced_and_marked_lossy():
    data = b"\xff\xfe" + b"a\x00b\x00" + b"\xff"  # UTF-16-LE BOM, then an odd byte
    result = textio.decode_text(data, NO_EXT)
    assert result is not None
    text, lossy = result
    assert lossy is True
    assert text.startswith("ab") and "�" in text


def test_utf8_bom_with_undecodable_body_keeps_the_prefix():
    data = b"\xef\xbb\xbf" + b"ok\xff"
    text, lossy = textio.decode_text(data, NO_EXT) or ("", False)
    assert lossy is True and text == "ok�"


# -- decode_text: the 8 KB NUL sniff window is exactly 8192 bytes ------------
# kills x_decode_text__mutmut_24


def test_nul_at_byte_8192_is_outside_the_sniff_window():
    data = b"x" * 8192 + b"\x00" + b"y"
    assert textio.decode_text(data, NO_EXT) is not None  # text, not binary


def test_nul_at_byte_8191_is_inside_the_sniff_window():
    data = b"x" * 8191 + b"\x00" + b"y"
    assert textio.decode_text(data, NO_EXT) is None  # binary verdict


# -- human_size: exact values at and around both boundaries ------------------
# kills x_human_size__mutmut_1,3,4,9,10 (boundaries) and 5,6,7,8,11,12 (arithmetic)


def test_human_size_exact_values():
    assert textio.human_size(0) == "0 bytes"
    assert textio.human_size(1023) == "1023 bytes"
    assert textio.human_size(1024) == "1.0 KB"  # >= 1024, not > 1024
    assert textio.human_size(2048) == "2.0 KB"
    assert textio.human_size(100 * 1024) == "100.0 KB"  # n / 1025 would show 99.9
    assert textio.human_size(1024 * 1024 - 1) == "1024.0 KB"
    assert textio.human_size(1024 * 1024) == "1.0 MB"  # >= 1 MiB, not > 1 MiB
    assert textio.human_size(2 * 1024 * 1024) == "2.0 MB"
    assert textio.human_size(100 * 1024 * 1024) == "100.0 MB"  # /1025 shows 99.9
