"""Property tests (hypothesis) for the pure helpers the file tools rely on.

Roadmap item 1 of 2026-08-31: the security invariant of the path guard,
a differential check of the pure-Python glob matcher against the stdlib
one where it exists, and never-crash + bound invariants for the output
clipper and the text decoder. These are the places where a hand-written
example test only proves the cases someone thought of.

Settings: `deadline=None` because the path guard touches the filesystem
(`resolve()`) and the Pi is slow; examples are capped so the whole file
stays well inside the suite's 60 s per-test timeout.
"""

import pathlib
from pathlib import Path, PurePosixPath

import pytest
from fastmcp.exceptions import ToolError
from hypothesis import assume, example, given, settings
from hypothesis import strategies as st

from binnacle import jobs, paths, textio

# -- paths.resolve_path: inside an allowed root, or ToolError, never anything else


@settings(max_examples=400, deadline=None)
@given(st.text(min_size=0, max_size=200))
def test_resolve_path_is_inside_a_root_or_raises_tool_error(raw: str):
    """The guard's whole contract: for *any* string the model sends, the
    result is under an allowed root or the call fails as a ToolError. Any
    other exception would surface to the client as an internal error."""
    try:
        resolved = paths.resolve_path(raw)
    except ToolError:
        return
    assert resolved.is_absolute()
    assert any(resolved.is_relative_to(root) for root in paths.ALLOWED_ROOTS), resolved


@settings(max_examples=300, deadline=None)
@given(
    st.lists(
        st.sampled_from(["..", ".", "~", "@", "/", "\0", "etc", "passwd", " ", "x"]),
        min_size=1,
        max_size=12,
    ).map("".join)
)
def test_resolve_path_traversal_shapes_never_escape(raw: str):
    """Adversarial alphabet: dot-dot, tilde, the hallucinated '@' prefix,
    NULs and absolute jumps, in every combination."""
    try:
        resolved = paths.resolve_path(raw)
    except ToolError:
        return
    assert any(resolved.is_relative_to(root) for root in paths.ALLOWED_ROOTS), resolved


def test_resolve_path_examples_that_must_escape_are_refused():
    for raw in ("/etc/passwd", "../../../../etc/passwd", "~/../../etc", "/"):
        with pytest.raises(ToolError):
            paths.resolve_path(raw)


# -- paths.full_match: differential against PurePath.full_match (3.13+)

GLOB_ALPHABET = st.sampled_from(list("ab./*?[]!-^\\"))
PATH_ALPHABET = st.sampled_from(list("ab./-"))
# Looked up dynamically: the method exists from 3.13, and mypy checks this
# file against the project's 3.10 floor, where a direct call would not type.
STDLIB_FULL_MATCH = getattr(pathlib.PurePath, "full_match", None)


@pytest.mark.skipif(
    STDLIB_FULL_MATCH is None,
    reason="PurePath.full_match needs Python 3.13; this interpreter has no reference",
)
@settings(max_examples=500, deadline=None)
@given(
    st.lists(PATH_ALPHABET, min_size=1, max_size=12).map("".join),
    st.lists(GLOB_ALPHABET, min_size=1, max_size=12).map("".join),
)
@example("/a/a", "**/a")  # ** spans the root: True in the stdlib (2026-09-13)
@example("/a", "**/a")  # but ** cannot absorb the bare root: False
@example("a\nb/c", "**")  # trailing ** is DOTALL `.*` in the stdlib
@example("a", "[^]")  # Python 3.14 fnmatch wrapper ends in \z, not \Z
@example("^", "[^]")  # ^ stays literal; only ! negates a glob class
def test_full_match_agrees_with_the_stdlib(path: str, pattern: str):
    """Our matcher exists only because 3.10-3.12 lack the stdlib one; on
    3.13+ both must answer alike, or a glob behaves differently per Python."""
    assume("//" not in path and not path.endswith("/"))
    assert STDLIB_FULL_MATCH is not None
    try:
        expected = STDLIB_FULL_MATCH(PurePosixPath(path), pattern)
    except ValueError:
        # The stdlib refuses the pattern; ours must refuse it too, the same way.
        with pytest.raises(ValueError):
            paths.full_match(path, pattern)
        return
    assert paths.full_match(path, pattern) == expected, (path, pattern)


def test_unwrap_fnmatch_translation_accepts_legacy_and_py314_anchors():
    assert paths._unwrap_fnmatch_translation(r"(?s:[\^])\Z") == r"[\^]"
    assert paths._unwrap_fnmatch_translation(r"(?s:[\^])\z") == r"[\^]"
    assert paths._unwrap_fnmatch_translation(r"unexpected") is None


@pytest.mark.parametrize(
    ("path", "pattern", "expected"),
    [
        ("a", "[^]", False),
        ("^", "[^]", True),
        ("a", "[!!!]", True),
        ("!", "[!!!]", False),
        ("]", "[]]", True),
        ("a", "[a-.]", False),
        ("-", "[--]", True),
        ("\\", r"[\\]", True),
        ("[", "[", True),
    ],
)
def test_full_match_character_class_regressions(
    path: str, pattern: str, expected: bool
):
    assert paths.full_match(path, pattern) is expected


@settings(max_examples=200, deadline=None)
@given(
    st.lists(PATH_ALPHABET, min_size=1, max_size=12).map("".join),
    st.lists(GLOB_ALPHABET, min_size=1, max_size=12).map("".join),
)
def test_full_match_never_raises_anything_but_value_error(path: str, pattern: str):
    """The callers' contract is `except ValueError -> ToolError`; a regex
    error escaping as re.error would be an internal error to the client."""
    try:
        result = paths.full_match(path, pattern)
    except ValueError:
        return
    assert isinstance(result, bool)


# -- jobs.clip_head_tail: bounded, prefix and suffix preserved, marker honest


@settings(max_examples=300, deadline=None)
@given(st.text(max_size=3000), st.integers(min_value=0, max_value=2500))
def test_clip_head_tail_bounds_and_preserves_both_ends(text: str, limit: int):
    out, clipped = jobs.clip_head_tail(text, limit)
    if len(text) <= limit:
        assert (out, clipped) == (text, False)
        return
    assert clipped is True
    head = limit // 2
    tail = limit - head
    omitted = len(text) - limit
    marker = f"\n[… {omitted} chars elided …]\n"
    assert out.startswith(text[:head])
    assert out.endswith(text[len(text) - tail :])
    assert marker in out
    # Bounded: never more than the limit plus the marker itself.
    assert len(out) == limit + len(marker), (len(text), limit, len(out))


def test_clip_head_tail_limit_zero_keeps_nothing_but_the_marker():
    """limit=0 is the degenerate edge: no head, no tail, only the marker."""
    out, clipped = jobs.clip_head_tail("abcdef", 0)
    assert clipped is True
    assert out == "\n[… 6 chars elided …]\n"


# -- textio.decode_text / human_size: never crash, decisions stay honest


@settings(max_examples=300, deadline=None)
@given(
    st.binary(max_size=4096), st.sampled_from([".py", ".md", ".bin", "", ".ts", ".dat"])
)
def test_decode_text_never_raises_and_returns_the_contract(data: bytes, suffix: str):
    result = textio.decode_text(data, Path(f"/tmp/probe{suffix}"))
    if result is None:
        # Binary verdict: only for unknown extensions with a NUL in the sniff window.
        assert suffix not in {".py", ".md", ".ts"}
        assert b"\0" in data[:8192]
        return
    text, lossy = result
    assert isinstance(text, str) and isinstance(lossy, bool)


@settings(max_examples=200, deadline=None)
@given(st.text(max_size=500))
def test_decode_text_round_trips_utf8_losslessly(text: str):
    data = text.encode("utf-8")
    assert textio.decode_text(data, Path("/tmp/x.txt")) == (text, False)


@settings(max_examples=200, deadline=None)
@given(
    st.sampled_from(
        [
            b"\xef\xbb\xbf",
            b"\xff\xfe",
            b"\xfe\xff",
            b"\xff\xfe\x00\x00",
            b"\x00\x00\xfe\xff",
        ]
    ),
    # U+0000 is excluded on purpose: UTF-16-LE BOM + NUL is FF FE 00 00,
    # byte-identical to the UTF-32-LE BOM, so the decoder must take the
    # longer BOM. That is the right call, not a defect (found 2026-09-13).
    st.text(alphabet=st.characters(min_codepoint=1, max_codepoint=0x7F), max_size=64),
)
def test_decode_text_honours_every_bom_even_for_unknown_extensions(
    bom: bytes, text: str
):
    """A BOM is decisive: the file is text whatever its name says."""
    codec = {
        b"\xef\xbb\xbf": "utf-8",
        b"\xff\xfe": "utf-16-le",
        b"\xfe\xff": "utf-16-be",
        b"\xff\xfe\x00\x00": "utf-32-le",
        b"\x00\x00\xfe\xff": "utf-32-be",
    }[bom]
    data = bom + text.encode(codec)
    result = textio.decode_text(data, Path("/tmp/no-extension"))
    assert result is not None
    assert result[0] == text


@settings(max_examples=200, deadline=None)
@given(st.integers(min_value=0, max_value=1 << 40))
def test_human_size_is_a_string_with_a_unit(n: int):
    s = textio.human_size(n)
    assert s.endswith((" bytes", " KB", " MB"))
    if n < 1024:
        assert s == f"{n} bytes"


def test_class_regex_falls_back_if_stdlib_wrapper_shape_changes(monkeypatch):
    monkeypatch.setattr(paths, "_unwrap_fnmatch_translation", lambda translated: None)
    assert paths._class_regex("abc") == "[abc]"


def test_glob_regex_converts_regex_compile_error_to_value_error(monkeypatch):
    paths._glob_regex.cache_clear()

    def boom(*args, **kwargs):
        raise paths.re.error("synthetic regex failure")

    monkeypatch.setattr(paths.re, "compile", boom)
    with pytest.raises(ValueError) as exc:
        paths._glob_regex("*.py")
    assert "synthetic regex failure" in str(exc.value)
    paths._glob_regex.cache_clear()


def test_nearby_hint_handles_outside_missing_empty_and_large_directory(
    tmp_path, monkeypatch
):
    root = tmp_path / "allowed"
    root.mkdir()
    monkeypatch.setattr(paths, "ALLOWED_ROOTS", (root,))

    assert paths.nearby_hint(tmp_path / "outside") == ""
    assert paths.nearby_hint(root / "missing") == ""

    empty = root / "empty"
    empty.mkdir()
    assert "is empty" in paths.nearby_hint(empty)

    crowded = root / "crowded"
    crowded.mkdir()
    for i in range(12):
        (crowded / f"f{i:02}.txt").write_text("x")
    hint = paths.nearby_hint(crowded)
    assert "f00.txt" in hint
    assert "…" in hint
    assert "list_files" in hint
