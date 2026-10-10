"""G5-G6 Gate A: root healthz still registered by the native FastMCP factory."""

from pathlib import Path

from scripts import gate_a_source as source


def test_current_pure_factory_must_register_healthz_and_bootstrap_delegate():
    root = Path(__file__).resolve().parents[2] / "src/binnacle"
    assert source.has_root_health_route(
        root / "application.py", factory_name="create_application"
    )
    assert source.has_delegated_root_health_route(
        root / "server.py", root / "application.py"
    )


def test_unwired_root_and_undeclared_routes_do_not_pass(tmp_path: Path):
    bootstrap = tmp_path / "server.py"
    pure = tmp_path / "application.py"
    bootstrap.write_text(
        "def create_server():\n"
        "    from binnacle.application import create_application\n"
        "    return other_application()\n"
    )
    pure.write_text(
        "def create_application():\n"
        "    root = FastMCP('x')\n"
        "    @root.custom_route('/healthz', methods=['GET'], include_in_schema=False)\n"
        "    def healthz(): pass\n"
        "    return root\n"
    )
    assert not source.has_delegated_root_health_route(bootstrap, pure)
    bootstrap.write_text(
        bootstrap.read_text().replace("other_application", "create_application")
    )
    assert source.has_delegated_root_health_route(bootstrap, pure)
    pure.write_text(
        pure.read_text().replace("include_in_schema=False", "include_in_schema=True")
    )
    assert not source.has_delegated_root_health_route(bootstrap, pure)
