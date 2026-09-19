import ast

from binnacle import indexed_parse as ip


def test_python_parser_covers_async_decorators_defaults_classes_and_attributes():
    parsed = ip.parse_python(
        "pkg/complex.py",
        """
@decorate
async def fetch(value=DEFAULT, *, limit=LIMIT) -> Result:
    return helper(obj.attr)

@decorate
class Child(Base, metaclass=Meta):
    @decorate
    def method(self):
        return helper()
""",
    )

    kinds = {(node.kind, node.symbol) for node in parsed.nodes}
    assert ("function", "fetch") in kinds
    assert ("class", "Child") in kinds
    assert ("function", "method") in kinds
    names = {item.name for item in parsed.identifiers}
    assert {"decorate", "DEFAULT", "LIMIT", "Result", "Base", "Meta", "attr"} <= names
    assert any(ref.name == "helper" for ref in parsed.refs)


def test_extractor_ignores_empty_identifier_and_module_body_skips_no_lineno():
    ex = ip.OnePassPythonExtractor("x.py", "")
    ex.add_ident("")
    assert ex.identifiers == []

    tree = ast.Module(body=[ast.Pass()], type_ignores=[])
    assert ip._module_body(tree, []) == ""


def test_markdown_empty_document_uses_default_title():
    parsed = ip.parse_markdown("empty.md", "")
    assert len(parsed.nodes) == 1
    assert parsed.nodes[0].symbol == "document"
    assert parsed.nodes[0].start_line == 1


def test_parse_config_caps_nodes_at_500():
    text = "\n".join(f"setting_{i:03} = {i}" for i in range(550))
    parsed = ip.parse_config("config/settings.ini", text)
    assert len(parsed.nodes) == 500
