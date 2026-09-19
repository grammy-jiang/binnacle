from binnacle.indexed_retrieval import PersistentRelationIndex
from tests.unit.core.test_indexed_index import make_repo


def test_empty_terms_missing_metadata_and_no_lexical_matches(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    index = PersistentRelationIndex(root, tmp_path / "index.db")

    assert index.terms("the and current") == []
    assert index.lexical_nodes("the and current") == []
    assert index.lexical_nodes("zzzz_no_such_symbol") == []
    assert index._node_meta([]) == {}

    monkeypatch.setattr(index, "lexical_nodes", lambda q, limit=180: ["ghost-node"])
    monkeypatch.setattr(index, "_node_meta", lambda ids: {})
    assert index.retrieve_evidence("ghost", 10) == []
    index.close()


def test_relation_intents_and_explicit_two_hop_call_chain(tmp_path):
    root = make_repo(tmp_path)
    (root / "src" / "entry.py").write_text(
        "from middle import middle_node\n\n"
        "def entry_point():\n"
        "    return middle_node()\n"
    )
    (root / "src" / "middle.py").write_text(
        "from leaf import leaf_node\n\ndef middle_node():\n    return leaf_node()\n"
    )
    (root / "src" / "leaf.py").write_text("def leaf_node():\n    return 1\n")
    index = PersistentRelationIndex(root, tmp_path / "index.db")
    try:
        tick = chr(96)
        two_hop = index.retrieve_evidence(
            f"follow {tick}entry_point{tick} exactly two hops downstream", 20
        )
        by_path = {str(item["path"]): str(item["reason"]) for item in two_hop}
        assert by_path["src/entry.py"] == "explicit entry symbol"
        assert by_path["src/middle.py"].startswith("call hop 1")
        assert by_path["src/leaf.py"].startswith("call hop 2")

        documented = index.retrieve_evidence(
            "documented storage persist_value normalization", 20
        )
        assert any("doc_ref" in str(item["reason"]) for item in documented)

        configured = index.retrieve_evidence(
            "configuration setting retry_limit consumer", 20
        )
        assert any("config_consumer" in str(item["reason"]) for item in configured)

        incoming = index.retrieve_evidence("leaf_node", 20)
        assert any(
            str(item["reason"]).startswith("source with call to") for item in incoming
        )
    finally:
        index.close()


def test_explicit_two_hop_handles_missing_or_short_entry_chain(tmp_path):
    root = make_repo(tmp_path)
    (root / "src" / "short.py").write_text("def short_entry():\n    return 1\n")
    index = PersistentRelationIndex(root, tmp_path / "index.db")
    try:
        tick = chr(96)
        missing = index.retrieve_evidence(
            f"follow {tick}does_not_exist{tick} exactly two hops downstream", 20
        )
        assert all(item["reason"] != "explicit entry symbol" for item in missing)

        short = index.retrieve_evidence(
            f"follow {tick}short_entry{tick} exactly two hops downstream", 20
        )
        assert any(item["reason"] == "explicit entry symbol" for item in short)
        assert not any(str(item["reason"]).startswith("call hop") for item in short)
    finally:
        index.close()


def test_context_package_falls_back_to_path_lookup_and_skips_missing_path(
    tmp_path, monkeypatch
):
    root = make_repo(tmp_path)
    index = PersistentRelationIndex(root, tmp_path / "index.db")

    monkeypatch.setattr(
        index,
        "retrieve_evidence",
        lambda q, k: [
            {
                "path": "src/app.py",
                "node_id": "missing-node",
                "score": 1.0,
                "reason": "synthetic relation",
            },
            {
                "path": "missing.py",
                "node_id": "also-missing",
                "score": 0.5,
                "reason": "synthetic missing",
            },
        ],
    )
    monkeypatch.setattr(index, "lexical_nodes", lambda q, limit=180: [])

    package = index.context_package(
        "synthetic",
        relation_items=2,
        lexical_items=0,
    )

    assert [item["path"] for item in package["related_context"]] == ["src/app.py"]
    assert package["related_context"][0]["reason"] == "synthetic relation"
    index.close()


def test_context_package_trims_and_drops_direct_then_related_items(tmp_path):
    root = make_repo(tmp_path)
    (root / "src" / "long.py").write_text(
        "def ultralong_sentinel():\n"
        '    """' + ("verylongtoken " * 120) + '"""\n'
        "    return 1\n"
    )
    index = PersistentRelationIndex(root, tmp_path / "index.db")

    direct = index.context_package(
        "ultralong_sentinel",
        relation_items=0,
        lexical_items=2,
        snippet_chars=700,
        max_bytes=180,
    )
    assert direct["structured_bytes"] <= 180
    assert direct["direct_matches"] == []

    related = index.context_package(
        "ultralong_sentinel",
        relation_items=1,
        lexical_items=0,
        snippet_chars=700,
        max_bytes=180,
    )
    assert related["structured_bytes"] <= 180
    assert related["related_context"] == []
    index.close()


def test_context_package_skips_lexical_node_without_metadata(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    index = PersistentRelationIndex(root, tmp_path / "index.db")
    try:
        monkeypatch.setattr(index, "retrieve_evidence", lambda q, k: [])
        monkeypatch.setattr(
            index,
            "lexical_nodes",
            lambda q, limit=180: ["missing-lexical-node"],
        )
        monkeypatch.setattr(index, "_node_meta", lambda ids: {})

        package = index.context_package(
            "synthetic",
            relation_items=0,
            lexical_items=2,
        )

        assert package["direct_matches"] == []
        assert package["related_context"] == []
    finally:
        index.close()


def test_context_package_extreme_budget_reaches_empty_package_break(tmp_path):
    root = make_repo(tmp_path)
    index = PersistentRelationIndex(root, tmp_path / "index.db")
    try:
        package = index.context_package(
            "normalize_value",
            relation_items=2,
            lexical_items=2,
            snippet_chars=160,
            max_bytes=1,
        )
        assert package["direct_matches"] == []
        assert package["related_context"] == []
        assert package["structured_bytes"] > 1
    finally:
        index.close()
