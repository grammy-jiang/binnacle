"""Negative preparation checks must fail before production migration exists."""

import subprocess

import pytest

import scripts.gate_a_manifest as manifest
import scripts.gate_a_report as gate_a


@pytest.mark.parametrize(
    "statement", ["from . import uplink", "from .uplink import probe"]
)
def test_relative_companion_import_is_visible(tmp_path, statement):
    source = tmp_path / "doctor_connectivity.py"
    source.write_text(statement)
    assert "binnacle.uplink" in gate_a.imports_for(source)


@pytest.mark.parametrize(
    ("statement", "expected"),
    [
        ("from .tunnel_unit import TUNNEL_UNIT", ({"TUNNEL_UNIT"}, False)),
        ("from binnacle import tunnel_unit", (set(), True)),
        ("from . import tunnel_unit", (set(), True)),
    ],
)
def test_tunnel_identity_import_spellings(tmp_path, statement, expected):
    source = tmp_path / "watchdog_cli.py"
    source.write_text(statement)
    assert gate_a.imported_names_from(source, "binnacle.tunnel_unit") == expected


def test_domain_scan_covers_manifest():
    groups = manifest.manifest_groups()
    expected = set.union(*(groups[g] for g in ("files", "search", "commands")))
    assert {
        p.relative_to(gate_a.SRC).as_posix() for p in gate_a.product_domain_files()
    } == expected


def test_doctor_common_is_explicit_compatibility_facade():
    assert "doctor_common.py" in manifest.compatibility_facades()


@pytest.mark.parametrize(
    ("path", "methods", "schema", "owner"),
    [
        ("/elsewhere", '["GET"]', "False", "create_server"),
        ("/healthz", '["POST"]', "False", "create_server"),
        ("/healthz", '["GET", "POST"]', "False", "create_server"),
        ("/healthz", '["GET"]', "True", "create_server"),
        ("/healthz", '["GET"]', "False", "create_child"),
        ("/healthz", '["GET"]', "False", "create_server"),
    ],
)
def test_health_route_registration_shape(
    tmp_path, monkeypatch, path, methods, schema, owner
):
    monkeypatch.setattr(gate_a, "SRC", tmp_path)
    (tmp_path / "server.py").write_text(
        f"def {owner}():\n    root = FastMCP()\n"
        f"    @root.custom_route({path!r}, methods={methods}, include_in_schema={schema})\n"
        "    async def health(request): pass\n    return root\n"
    )
    assert gate_a.has_custom_route() == (
        path == "/healthz"
        and methods == '["GET"]'
        and schema == "False"
        and owner == "create_server"
    )


def test_unrelated_child_route_is_not_root_health(tmp_path, monkeypatch):
    monkeypatch.setattr(gate_a, "SRC", tmp_path)
    (tmp_path / "server.py").write_text("def create_server(): pass")
    (tmp_path / "files_server.py").write_text(
        '@child.custom_route("/healthz")\ndef health(): pass'
    )
    assert not gate_a.has_custom_route()


@pytest.mark.parametrize("dirty", ["tracked", "untracked", None])
def test_source_snapshot_requires_clean_tree(tmp_path, monkeypatch, dirty):
    for name in subprocess.check_output(
        ["git", "rev-parse", "--local-env-vars"], text=True
    ).splitlines():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(gate_a, "ROOT", tmp_path)

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(tmp_path), *args], check=True, capture_output=True
        )

    git("init", "-q")
    (tmp_path / "source.py").write_text("pass\n")
    git("add", "source.py")
    git(
        "-c",
        "user.name=test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-qm",
        "base",
    )
    if dirty:
        (tmp_path / ("source.py" if dirty == "tracked" else "new.py")).write_text(
            "# dirty\n"
        )
    assert (gate_a.clean_snapshot() is not None) == (dirty is None)


@pytest.mark.parametrize(
    ("before", "after", "bound"),
    [("a" * 40, "a" * 40, True), ("a" * 40, "b" * 40, False), (None, "a" * 40, False)],
)
def test_source_binding_wraps_report(monkeypatch, before, after, bound):
    events = []
    readings = iter([before, after])

    def snapshot():
        events.append("snapshot")
        return next(readings)

    monkeypatch.setattr(gate_a, "clean_snapshot", snapshot)
    monkeypatch.setattr(gate_a, "report", lambda: events.append("report") or [])
    payload = gate_a.collect_report()
    assert events == ["snapshot", "report", "snapshot"]
    assert payload["candidate"] == (before if bound else None)
    assert payload["cells"][0]["status"] == ("PASS" if bound else "FAIL")


@pytest.mark.parametrize(
    ("names", "direct", "passes"),
    [
        ({"TUNNEL_UNIT"}, False, True),
        (set(), False, False),
        ({"TUNNEL_UNIT", "render_tunnel_unit"}, False, False),
        (set(), True, False),
    ],
)
def test_report_requires_exact_tunnel_identity(monkeypatch, names, direct, passes):
    monkeypatch.setattr(gate_a, "imported_names_from", lambda *_: (names, direct))
    cell = next(
        c for c in gate_a.report() if c.id == "companion.watchdog_tunnel_unit_contract"
    )
    assert (cell.status == "PASS") == passes


@pytest.mark.parametrize("module", ["uplink", "watchdog_config", "tunnel_doctor"])
def test_new_diagnostics_module_cannot_bridge_companions(tmp_path, monkeypatch, module):
    monkeypatch.setattr(gate_a, "ROOT", tmp_path)
    monkeypatch.setattr(gate_a, "SRC", tmp_path)
    groups = {
        "diagnostics": {"new_diagnostic.py"},
        "watchdog": {"uplink.py", "watchdog_config.py"},
        "tunnel": {"tunnel_doctor.py"},
    }
    monkeypatch.setattr(gate_a, "manifest_groups", lambda: groups)
    (tmp_path / "new_diagnostic.py").write_text(f"from .{module} import something\n")
    assert gate_a.any_import(
        gate_a.group_paths("diagnostics"), gate_a.companion_modules()
    )


def test_command_store_linux_dependency_is_visible(tmp_path, monkeypatch):
    monkeypatch.setattr(gate_a, "ROOT", tmp_path)
    monkeypatch.setattr(gate_a, "SRC", tmp_path)
    monkeypatch.setattr(
        gate_a,
        "manifest_groups",
        lambda: {"files": set(), "search": set(), "commands": {"job_store.py"}},
    )
    (tmp_path / "job_store.py").write_text(
        "from binnacle.platform.linux.job_cgroup import snapshot\n"
    )
    assert gate_a.any_import(
        gate_a.product_domain_files(), ("binnacle.platform.linux.job_cgroup",)
    )


def test_doctor_prefix_does_not_forbid_neutral_render_helper(tmp_path, monkeypatch):
    monkeypatch.setattr(gate_a, "ROOT", tmp_path)
    source = tmp_path / "watchdog_cli.py"
    source.write_text("from binnacle.doctor_render import render\n")
    assert gate_a.any_import([source], ("binnacle.doctor",)) == []


def test_snapshot_ignores_inherited_repository_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "nonexistent.git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(tmp_path))
    assert gate_a.current_sha() is not None
    assert "GIT_DIR" not in gate_a.git_environment()
    assert "GIT_WORK_TREE" not in gate_a.git_environment()
