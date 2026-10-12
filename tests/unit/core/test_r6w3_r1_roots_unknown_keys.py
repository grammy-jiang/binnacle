"""Unknown roots keys fail startup instead of leaving the default roots in force.

TEST-FOLLOWUP-roots-settings-unknown-kwargs (r6 W3 R1): RootsSettings used to
ignore an unknown key, so ``RootsSettings(allowed=...)`` and a misspelled
``[roots]`` key in a host config ran with ~/Projects + /tmp. The error names
every bad key and the valid keys. Foreign top-level sections such as the
watchdog's ``[watchdog]`` table stay valid.
"""

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from binnacle import config

VALID = "valid [roots] keys: default_root, extra_roots"


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    for key in tuple(os.environ):
        if key.startswith("BINNACLE_"):
            monkeypatch.delenv(key, raising=False)
    path = tmp_path / "config.toml"
    monkeypatch.setenv(config.CONFIG_FILE_ENV, str(path))
    return path


def startup_error(path: Path, text: str) -> str:
    path.write_text(text)
    with pytest.raises(ValidationError) as caught:
        config.Settings()
    return str(caught.value)


def test_valid_keys_are_the_model_fields():
    assert config.ROOTS_KEYS == tuple(config.RootsSettings.model_fields)


def test_unknown_kwarg_names_the_key_and_the_valid_keys(tmp_path):
    with pytest.raises(ValidationError) as caught:
        config.RootsSettings(default_root=tmp_path, allowed=[tmp_path])
    message = str(caught.value)
    assert "unknown [roots] key(s) 'allowed'" in message
    assert VALID in message


def test_every_unknown_key_is_named_in_sorted_order():
    with pytest.raises(ValidationError) as caught:
        config.RootsSettings.model_validate({"zeta": 1, "alpha": 2})
    assert "unknown [roots] key(s) 'alpha', 'zeta'" in str(caught.value)


def test_misspelled_key_in_the_roots_table_fails_startup(config_file):
    message = startup_error(config_file, '[roots]\ndefault_roots = "/srv/work"\n')
    assert "unknown [roots] key(s) 'default_roots'" in message
    assert VALID in message


@pytest.mark.parametrize(
    "text,key",
    [
        ('[root]\ndefault_root = "/srv/work"\n', "root"),
        ('[Root]\nextra_roots = ["/srv"]\n', "Root"),
        ('default_root = "/srv/work"\n', "default_root"),
        ('extra_roots = ["/srv"]\n', "extra_roots"),
    ],
)
def test_roots_like_top_level_key_fails_startup(config_file, text, key):
    message = startup_error(config_file, text)
    assert f"unknown top-level roots-like key(s) {key!r}" in message
    assert VALID in message


def test_case_variant_section_is_the_roots_table(config_file):
    # pydantic-settings matches top-level names case-insensitively, so [Roots]
    # is applied as [roots] (never ignored) and its keys are checked.
    config_file.write_text('[Roots]\nextra_roots = ["/srv"]\n')
    assert config.Settings().roots.extra_roots == (Path("/srv"),)
    message = startup_error(config_file, '[Roots]\nextra_root = ["/srv"]\n')
    assert "unknown [roots] key(s) 'extra_root'" in message


def test_unknown_env_roots_key_fails_startup(config_file, monkeypatch):
    monkeypatch.setenv("BINNACLE_ROOTS__ALLOWED", "/srv")
    with pytest.raises(ValidationError, match="unknown \\[roots\\] key"):
        config.Settings()


def test_valid_roots_table_is_unchanged(config_file, tmp_path):
    config_file.write_text(
        f'[roots]\ndefault_root = "{tmp_path}"\nextra_roots = ["/var/tmp"]\n'
    )
    roots = config.Settings().roots
    assert roots.default_root == tmp_path
    assert roots.extra_roots == (Path("/var/tmp"),)
    assert roots.allowed == (tmp_path, Path("/var/tmp"))


def test_production_shaped_config_stays_valid(config_file):
    # The key names of the Pi production config (2026-10-12), synthetic values.
    config_file.write_text(
        """
[watchdog]
driver_reload_enabled = false
inventory_params = []
usb_reset_ids = []
usb_link_policies = []

[search_text]
adaptive_discovery_enabled = true

[telemetry.tokenizer]
enabled = true
encoding = "o200k_base"
client_prefixes = ["openai-mcp"]

[run_command]
auto_background_evidence_retention_days = 7

[run_command.auto_background_patterns]
"openai-mcp" = ["pytest"]

[indexed_context]
enabled = true
"""
    )
    settings = config.Settings()
    assert settings.roots.allowed == config.RootsSettings().allowed
    assert settings.removed_sections == ("indexed_context",)


@pytest.mark.parametrize("key", ["serve", "jobs", "tools", "watchdog", "rot"])
def test_other_keys_are_not_roots_like(key):
    assert not config.roots_like(key)


def test_model_instance_and_defaults_still_validate(config_file, tmp_path):
    roots = config.RootsSettings(default_root=tmp_path, extra_roots=())
    assert config.Settings(roots=roots).roots.allowed == (tmp_path,)
    assert config.RootsSettings().extra_roots == (Path("/tmp"),)
