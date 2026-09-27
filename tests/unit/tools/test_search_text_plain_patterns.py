"""search_text after the removal of the '@context' pilot (2026-09-28).

A pattern that starts with '@context ' is an ordinary regex or literal
pattern again, with no special case: no argument check, no Git-root rule, no
index. Every other search keeps the exact results of master 9b7d6d3: the
digests below were measured there before the removal and on this branch
after it, on the same fixture tree (docs/indexed-context-pilot.md).
"""

import hashlib
import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastmcp.exceptions import ToolError

from binnacle.tools import search_text as st


def run(pattern: str, path: Path, **kw: Any):
    args: dict[str, Any] = {
        "glob": None,
        "fixed_strings": False,
        "context_lines": None,
        "names_only": False,
        "max_results": 100,
    }
    args.update(kw)
    return st.search_text_impl(pattern, str(path), **args)


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    (tmp_path / "a.py").write_text("def alpha():\n    return 1\n\nWIDGET = 9\n")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.py").write_text("def beta():\n    return WIDGET\n")
    (tmp_path / "notes.txt").write_text(
        "widget notes\n@context widget\ncontext widget\n@context wodget\n"
    )
    (tmp_path / "lit.txt").write_text("a.*b\nfoo\n")
    (tmp_path / "many.txt").write_text("hit\n" * 10)
    (tmp_path / "wide.txt").write_text("needle " + "z" * 5000 + "\n")
    return tmp_path


# -- '@context' is an ordinary pattern ----------------------------------------


def _git_root(tree: Path) -> Path:
    """The pilot's trigger: the path is a Git worktree root."""
    subprocess.run(["git", "init", "-q", str(tree)], check=True)
    return tree


def lines_of(payload: dict) -> list[str]:
    return sorted(entry["text"] for entry in payload["entries"])


def test_context_prefix_is_a_regex_at_the_worktree_root(tree):
    root = _git_root(tree)
    payload = run("@context w.dget", root, context_lines=0).structured_content
    assert payload is not None
    assert lines_of(payload) == ["@context widget", "@context wodget"]


def test_context_prefix_is_a_literal_with_fixed_strings(tree):
    root = _git_root(tree)
    payload = run(
        "@context w.dget", root, fixed_strings=True, context_lines=0
    ).structured_content
    assert payload is not None
    assert payload["count"] == 0
    payload = run(
        "@context widget", root, fixed_strings=True, context_lines=0
    ).structured_content
    assert payload is not None
    assert lines_of(payload) == ["@context widget"]


def test_context_prefix_without_a_query_is_searched_as_written(tree):
    # The pilot refused an empty query; now it is the text "@context ".
    payload = run("@context ", _git_root(tree), context_lines=0).structured_content
    assert payload is not None
    assert payload["count"] == 2


def test_context_prefix_takes_every_argument(tree):
    # The pilot refused glob, names_only, context_lines and max_results.
    payload = run(
        "@context w",
        tree,
        glob="*.txt",
        names_only=True,
        context_lines=2,
        max_results=5,
        line_numbers=True,
    ).structured_content
    assert payload is not None
    assert [(Path(e["file"]).name, e["count"]) for e in payload["entries"]] == [
        ("notes.txt", 2)
    ]


def test_context_prefix_outside_a_worktree_is_no_error(tree):
    # The pilot required a Git worktree; a plain directory now just searches.
    payload = run("@context w", tree, context_lines=0).structured_content
    assert payload is not None
    assert payload["count"] == 2


def test_dispatch_line_says_exact_for_a_context_prefix(tree, caplog):
    with caplog.at_level(logging.INFO, logger=st.log.name):
        run("@context widget", _git_root(tree), context_lines=0)
    lines = [
        r.getMessage()
        for r in caplog.records
        if r.getMessage().startswith("event=search_dispatch ")
    ]
    assert len(lines) == 1
    assert re.fullmatch(
        r"event=search_dispatch call=\S+ mode=exact path_hash=[0-9a-f]{12} "
        r"pattern_chars=15",
        lines[0],
    )


# -- every other search: the results of master 9b7d6d3 -------------------------


GOLDEN: dict[str, tuple[str, str, dict[str, Any]]] = {
    # id: (pattern, path relative to the tree, arguments)
    "regex": ("def alpha", ".", {"context_lines": 0}),
    "smart-case-lower": ("widget", ".", {"context_lines": 0}),
    "smart-case-upper": ("WIDGET", ".", {"context_lines": 0}),
    "fixed-strings": ("a.*b", ".", {"fixed_strings": True, "context_lines": 0}),
    "glob": ("widget", ".", {"glob": "*.py", "context_lines": 0}),
    "names-only": ("widget", ".", {"names_only": True}),
    "explicit-context": ("return 1", ".", {"context_lines": 1}),
    "auto-context-single": ("def beta", ".", {}),
    "auto-context-many": ("hit", "many.txt", {}),
    "max-results": ("hit", "many.txt", {"max_results": 4, "context_lines": 0}),
    "line-numbers": ("return 1", ".", {"context_lines": 1, "line_numbers": True}),
    "clipped-line": ("needle", "wide.txt", {"context_lines": 0}),
    "file-path": ("alpha", "a.py", {"context_lines": 0}),
    "no-match": ("nomatch_xyz", ".", {}),
    "literal-context-prefix": (
        "@context widget",
        ".",
        {"fixed_strings": True, "context_lines": 0},
    ),
}
# Measured on master 9b7d6d3 and on this branch: the same for every case.
GOLDEN_SHA256 = dict(
    line.split()
    for line in """
auto-context-many       60b0636f357f96425597aeb67441b4a153b4c3cf48f2d4d316242de6067ff371
auto-context-single     9a61984fc69f1fa075e35a58a41ea60606250819e54d7c2bd7c118e897d7cca3
clipped-line            9a9d583eaf7a4e4b108d703f168e4ce1def89d02d29a049ce29fb30291f4334d
explicit-context        829333aa2cd7675602eddf2f6b81799553f4ef6533a13b2575578b03f41abe5e
file-path               aa959e5b173be167978b12ee847f54ac253530b335504edcff54a6722c8458a1
fixed-strings           9a57b66e43b727cd984444e5b9f4e66a64ab32fd6446a414e1122aff3c17434d
glob                    193e9e0561f56e3379ad94fb7684c3628e66efb571db0c328abd25213b084f5a
line-numbers            6c6412c19a09f9fd559b0a1c8eb1cb10687754334e8fc696ac8eebf67ab9be39
literal-context-prefix  d82baf212a807f75f82347e5937bc3c81504ddd1858b9d903e75d555055fbe5a
max-results             cd4d8e6ccf54454883b0121bf68b21282e08aacf337790d08f005a54b16eb75d
names-only              a892efbba22a3c16b9ad1349b46666b3d18eb55b6cb8abfb7f2ae9b6a7e6812e
no-match                9e77dd2cf74095d8062cc870a2f3e5bb572efc92b3bcbfb9c1d0b77537dfab89
regex                   59ec324a40b2ec7fe92e747a4d80fd053f3ab11e7b84a269690a50c3567a1bd1
smart-case-lower        479df6221ad4330af0d2fe3287cb4d2bcfeabf04830755cb872152dcb7d4527f
smart-case-upper        17ce553323a818412b5ea6ab3fa20c00d2d1ca62d2b65f12697a14152fefa13a
""".strip().splitlines()
)


def normalized(result: Any, root: Path) -> str:
    """The structured result and the text a client receives, root masked.

    rg's parallel walker fixes no file order (see
    tests/integration/test_search_text_streaming_equivalence.py), so the
    entries are sorted by file and line; key order is kept as sent.
    """
    payload = dict(result.structured_content)
    payload["entries"] = sorted(
        payload["entries"], key=lambda e: (e["file"], e.get("line", 0))
    )
    texts = [block.text for block in result.content]
    sent = json.dumps({"structured": payload, "text": texts}, ensure_ascii=False)
    return sent.replace(str(root), "<root>")


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_results_are_those_of_master(name, tree):
    pattern, relative, args = GOLDEN[name]
    sent = normalized(run(pattern, tree / relative, **args), tree)
    digest = hashlib.sha256(sent.encode("utf-8")).hexdigest()
    assert digest == GOLDEN_SHA256[name], sent


@pytest.mark.parametrize(
    ("pattern", "relative", "message"),
    [
        ("", ".", "The 'pattern' parameter must be non-empty."),
        ("x", "nope", "Path not found: <root>/nope."),
    ],
)
def test_errors_are_those_of_master(pattern, relative, message, tree):
    with pytest.raises(ToolError) as exc:
        run(pattern, tree / relative)
    assert str(exc.value).replace(str(tree), "<root>").startswith(message)
