"""F2 regression: an external failure must not hide Binnacle importer origin."""

from pathlib import Path
from types import FunctionType

import pytest

from binnacle import startup_imports as startup


def _source_at(func: FunctionType, filename: str) -> None:
    """Label test-owned code objects without importing or executing files."""
    func.__code__ = func.__code__.replace(co_filename=filename)


def test_external_nested_failure_prefers_binnacle_importer_frame():
    binnacle_root = Path(startup.__file__).resolve().parent

    def dependency():
        raise ModuleNotFoundError("secret_from_dependency")

    def importer():
        return dependency()

    _source_at(dependency, "/tmp/e1a6-thirdparty-inner.py")
    _source_at(importer, str(binnacle_root / "synthetic_e1a6_importer.py"))
    with pytest.raises(ModuleNotFoundError) as caught:
        importer()
    where = startup._raising_frame(caught.value, "binnacle.synthetic_e1a6_importer")
    assert where == (
        f"binnacle/synthetic_e1a6_importer.py:{importer.__code__.co_firstlineno + 1}"
    )


def test_external_failure_with_no_binnacle_source_names_requested_module():
    def dependency():
        raise RuntimeError("secret_from_dependency")

    _source_at(dependency, "/tmp/e1a6-thirdparty-inner.py")
    with pytest.raises(RuntimeError) as caught:
        dependency()
    assert startup._raising_frame(caught.value, "binnacle.some_target") == (
        "binnacle.some_target:0"
    )


def test_source_of_direct_required_import_retains_location_even_outside_package():
    def dependency():
        raise RuntimeError("a secret")

    _source_at(dependency, "/tmp/e1a6_direct_target.py")
    with pytest.raises(RuntimeError) as caught:
        dependency()
    where = startup._raising_frame(caught.value, "e1a6_direct_target")
    assert where == f"e1a6_direct_target.py:{dependency.__code__.co_firstlineno + 1}"


def test_syntax_error_keeps_its_own_source_position():
    with pytest.raises(SyntaxError) as caught:
        compile("def broken(:", "/tmp/e1a6-bad-syntax.py", "exec")
    assert startup._raising_frame(caught.value, "binnacle.e1a6") == (
        "e1a6-bad-syntax.py:1"
    )
