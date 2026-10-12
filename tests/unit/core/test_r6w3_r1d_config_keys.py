"""R1D: the doctor WARNs on config keys Settings() ignores (key paths only)."""

import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from binnacle.config import CONFIG_FILE_ENV, Settings
from binnacle.config_unknown_keys import FOREIGN_TABLES, ignored_key_paths
from binnacle.diagnostics import doctor
from binnacle.diagnostics.doctor_config_keys import GROUP, check_config_keys

SENTINEL = "SENTINEL-r1d-7f3a"  # a value that must never reach any output

# Key structure of the production configs (R1-REPORT), with benign values.
PI_SHAPE = """
rg_bin = "rg"
[watchdog]
interval_s = 30
[[watchdog.usb_link_policies]]
usb_id = "1234:5678"
[search_text]
timeout_s = 20
[telemetry.tokenizer]
enabled = true
[run_command]
wait_default_s = 30
"""

MAC_SHAPE = """
[auth]
token_file = "/x/token"
[roots]
default_root = "/x/Projects"
extra_roots = ["/x/tmp"]
[serve]
port = 8000
"""

TEST_ROOT = Path.home() / ".local" / "state" / "bt" / "r1d"


@pytest.fixture
def cfg_dir() -> Iterator[Path]:
    """A private 0700 directory under ~/.local/state/bt/r1d, removed by exact path."""
    TEST_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix="cfg-", dir=TEST_ROOT))
    path.chmod(0o700)
    try:
        yield path
    finally:
        shutil.rmtree(path)


@pytest.fixture(autouse=True)
def _isolated_config(cfg_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings() must never read the host's real config file."""
    monkeypatch.setenv(CONFIG_FILE_ENV, str(cfg_dir / "absent.toml"))


def _write(cfg_dir: Path, text: str) -> Path:
    path = cfg_dir / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def _check(cfg_dir: Path, text: str):
    return check_config_keys(_write(cfg_dir, text))


def _warns(checks) -> dict[str, str]:
    assert all(c.status == "warn" and c.group == GROUP for c in checks), checks
    return {c.detail: c.hint for c in checks}


@pytest.mark.parametrize("shape", [PI_SHAPE, MAC_SHAPE], ids=["pi", "mac"])
def test_production_shapes_are_ok(cfg_dir: Path, shape: str) -> None:
    (check,) = _check(cfg_dir, shape)
    assert check.status == "ok"
    assert check.group == GROUP


def test_missing_file_is_ok(cfg_dir: Path) -> None:
    (check,) = check_config_keys(cfg_dir / "absent.toml")
    assert check.status == "ok"
    assert "no config file" in check.detail


def test_unknown_key_in_known_section_warns_with_near_miss(cfg_dir: Path) -> None:
    checks = _check(cfg_dir, f'[search_text]\ntimout_s = "{SENTINEL}"\n')
    ((detail, hint),) = _warns(checks).items()
    assert "`search_text.timout_s`" in detail
    assert "`search_text.timeout_s`" in hint


def test_unknown_top_level_table_warns_with_near_miss(cfg_dir: Path) -> None:
    checks = _check(cfg_dir, "[serch_text]\ntimeout_s = 1\n[zzz_unrelated]\nx = 1\n")
    warns = _warns(checks)
    assert len(warns) == 2
    near = {d: h for d, h in warns.items() if "serch_text" in d}
    assert "`search_text`" in next(iter(near.values()))
    far = {d: h for d, h in warns.items() if "zzz_unrelated" in d}
    assert "did you mean" not in next(iter(far.values()))


def test_foreign_table_is_allowlisted_and_not_walked(cfg_dir: Path) -> None:
    assert set(FOREIGN_TABLES) == {"watchdog"}
    assert all(owner for owner in FOREIGN_TABLES.values())
    text = "[watchdog]\nanything_goes = 1\n[watchdog.nested]\nmore = 2\n"
    (check,) = _check(cfg_dir, text)
    assert check.status == "ok"


def test_misspelt_foreign_table_hints_the_owner_table(cfg_dir: Path) -> None:
    ((detail, hint),) = _warns(_check(cfg_dir, "[watchdgo]\ninterval_s = 1\n")).items()
    assert "`watchdgo`" in detail
    assert "`watchdog`" in hint


def test_nested_table_unknown_key_uses_dotted_path(cfg_dir: Path) -> None:
    checks = _check(cfg_dir, "[telemetry.tokenizer]\nenabld = true\nenabled = true\n")
    ((detail, hint),) = _warns(checks).items()
    assert "`telemetry.tokenizer.enabld`" in detail
    assert "`telemetry.tokenizer.enabled`" in hint


def test_nested_keys_are_case_sensitive_but_top_level_is_not(cfg_dir: Path) -> None:
    # Probe-verified: [Search_Text] is applied; [serve] Port is ignored.
    checks = _check(cfg_dir, "[Search_Text]\ntimeout_s = 7\n[serve]\nPort = 9\n")
    ((detail, hint),) = _warns(checks).items()
    assert "`serve.Port`" in detail
    assert "`serve.port`" in hint


@pytest.mark.parametrize(
    ("text", "path"),
    [
        ("[indexed_context]\nx = 1\n", "indexed_context"),
        ("[run_command.shadow_prediction]\nx = 1\n", "run_command.shadow_prediction"),
        (
            "[jobs]\nblocking_wall_budget_s_by_client = 1\n",
            "jobs.blocking_wall_budget_s_by_client",
        ),
    ],
)
def test_removed_keys_warn_as_removed(cfg_dir: Path, text: str, path: str) -> None:
    ((detail, hint),) = _warns(_check(cfg_dir, text)).items()
    assert path in detail
    assert "removed" in detail
    assert "delete" in hint


def test_dict_valued_fields_are_not_walked(cfg_dir: Path) -> None:
    text = (
        "[run_command.auto_background_patterns]\n"
        'any-client-prefix = ["^make"]\n'
        "[client_tools]\n"
        'some-client = ["read_file"]\n'
    )
    (check,) = _check(cfg_dir, text)
    assert check.status == "ok"


def test_roots_problems_are_left_to_startup(cfg_dir: Path) -> None:
    # Rejected at start-up (config check FAILs), so this check stays silent.
    assert (
        ignored_key_paths({"roots": {"allowed": []}, "root": {}, "default_root": "/x"})
        == []
    )
    with pytest.raises(Exception, match="unknown"):
        Settings(roots={"allowed": []})
    (check,) = check_config_keys(_write(cfg_dir, "[roots]\nallowed = []\n"))
    assert check.status == "ok"


def test_unparsable_file_fails_without_echoing_values(cfg_dir: Path) -> None:
    (check,) = _check(cfg_dir, f'token = "{SENTINEL}" garbage\n')
    assert check.status == "fail"
    assert SENTINEL not in check.detail + check.hint


def test_directory_path_is_treated_as_no_file_like_settings(cfg_dir: Path) -> None:
    (check,) = check_config_keys(cfg_dir)
    assert check.status == "ok"
    assert "no config file" in check.detail


def test_values_never_appear_in_any_output(cfg_dir: Path) -> None:
    text = (
        f'[serch_text]\nkey = "{SENTINEL}"\n[search_text]\ntimout_s = "{SENTINEL}"\n'
        f'[run_command.auto_background_patterns]\nc = ["{SENTINEL}"]\n'
    )
    checks = _check(cfg_dir, text)
    assert len(checks) == 2
    assert SENTINEL not in repr(checks)


def test_env_path_is_the_same_file_settings_uses(
    cfg_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write(cfg_dir, "[serve]\npoort = 1\n")
    monkeypatch.setenv(CONFIG_FILE_ENV, str(path))
    ((detail, hint),) = _warns(check_config_keys()).items()
    assert "`serve.poort`" in detail
    assert "`serve.port`" in hint
    # Behavior of Settings() is unchanged: the ignored key still loads cleanly.
    assert Settings().serve.port == 8000


def test_every_settings_field_is_known() -> None:
    dumped = Settings().model_dump(mode="python")
    assert ignored_key_paths(dumped) == []


def test_run_all_registers_the_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dep = doctor.Deployment(
        server_unit="prod",
        token_file=tmp_path / "token",
        server_url="http://127.0.0.1:8000/mcp",
        user_bin=tmp_path / "bin",
    )
    settings = SimpleNamespace(rg_bin="rg", jobs=SimpleNamespace(dir=tmp_path / "jobs"))
    monkeypatch.setattr(doctor, "get_settings", lambda: settings)
    monkeypatch.setattr(doctor, "create_service_inspector", lambda: object())
    monkeypatch.setattr(
        doctor, "runtime_provenance", lambda: SimpleNamespace(revision="abc")
    )
    for name in ("check_provenance", "check_token", "check_endpoint", "check_jobs"):
        monkeypatch.setattr(doctor, name, lambda *a, **k: [])
    for name in ("check_config", "check_rg_version", "check_boot"):
        monkeypatch.setattr(doctor, name, lambda *a, **k: [])
    monkeypatch.setattr(doctor, "check_units", lambda *a, **k: ([], None))
    monkeypatch.setattr(
        doctor, "check_config_keys", lambda: [doctor.ok(GROUP, "marker")]
    )
    assert [c.group for c in doctor.run_all(dep, probe=False)] == [GROUP]
