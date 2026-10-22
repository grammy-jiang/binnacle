"""P3.1 provider authorization classification without discovery/launch effects."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from binnacle.config import RootsSettings
from binnacle.config_development_intelligence import (
    DevelopmentIntelligenceSettings,
    DevelopmentProviderSettings,
)
from binnacle.features.development_intelligence.lsp_preview_server import (
    validate_private_profile,
)
from binnacle.features.development_intelligence.lsp_process_owner import (
    PrivatePyrightProcessOwner,
    ProviderLifecycleError,
)
from binnacle.features.development_intelligence.lsp_profile_assessment import (
    assess_provider_profile,
)
from binnacle.features.development_intelligence.lsp_provider_manager import (
    PrivateProviderManager,
    ProviderManagerError,
)


def _enabled_profile(**profile_values):
    return DevelopmentIntelligenceSettings(
        enabled=True,
        discovery_enabled=True,
        profiles={
            "pyright": DevelopmentProviderSettings(enabled=True, **profile_values)
        },
    )


def test_disabled_and_absent_profile_is_not_audited():
    defaults = assess_provider_profile(DevelopmentIntelligenceSettings())
    assert defaults.classification == "not_audited"
    assert defaults.reason == "feature_disabled"
    assert not hasattr(defaults, "profile_fingerprint")
    assert not defaults.private_launch_eligible and not defaults.read_eligible
    absent = assess_provider_profile(DevelopmentIntelligenceSettings(enabled=True))
    assert absent.reason == "profile_absent"
    assert not absent.private_launch_eligible


def test_explicitly_disabled_profile_never_has_launch_authority():
    settings = DevelopmentIntelligenceSettings(
        enabled=True, profiles={"pyright": DevelopmentProviderSettings()}
    )
    verdict = assess_provider_profile(settings)
    assert verdict.classification == "not_audited"
    assert verdict.reason == "profile_disabled"
    assert not hasattr(verdict, "profile_fingerprint")
    assert not verdict.private_launch_eligible


@pytest.mark.parametrize(
    "provider",
    (
        "pyright",
        "typescript",
        "clangd",
        "rust_analyzer",
        "marksman",
        "bash",
        "make",
        "yaml",
        "json",
    ),
)
def test_bare_executable_service_path_is_only_benchmark_admission(provider):
    profile = DevelopmentProviderSettings(
        enabled=True,
        source="service_path",
        executable="pyright-langserver",
        mode="benchmark_only",
    )
    settings = DevelopmentIntelligenceSettings(
        enabled=True, profiles={provider: profile}
    )
    verdict = assess_provider_profile(settings, provider)
    assert verdict.classification == "benchmark_only"
    assert verdict.reason == "benchmark_service_path"
    assert verdict.source == "service_path"
    assert not verdict.private_launch_eligible and not verdict.read_eligible


def test_declared_trusted_absolute_requires_extra_owner_checks_not_read_grant():
    settings = _enabled_profile(
        source="trusted_absolute",
        executable=sys.executable,
        mode="explicit_trust_only",
        languages=("python",),
    )
    verdict = assess_provider_profile(settings)
    assert verdict.classification == "explicit_trust_only"
    assert verdict.private_launch_eligible and not verdict.read_eligible
    assert verdict.reason == "operator_explicit_trust_required"
    # No absolute paths in the diagnostic object or its text representation.
    assert sys.executable not in repr(verdict)
    assert validate_private_profile(settings)


@pytest.mark.parametrize(
    "options",
    [
        {"argv": ("--createtypestub",)},
        {"env": {"PYRIGHT_SIDE_EFFECT": "1"}},
        {"argv": ("--stdio",), "env": {"CACHE_DIR": "/private"}},
    ],
)
def test_unaudited_process_options_never_admit_private_pyright(options):
    settings = _enabled_profile(
        source="trusted_absolute",
        executable=sys.executable,
        mode="explicit_trust_only",
        **options,
    )
    verdict = assess_provider_profile(settings)
    assert verdict.classification == "not_audited"
    assert verdict.reason == "unaudited_process_options"
    assert not verdict.private_launch_eligible and not verdict.read_eligible
    with pytest.raises(
        ValueError, match="private_pyright_preview_requires_trusted_profile"
    ):
        validate_private_profile(settings)


def test_service_path_with_explicit_trust_label_is_not_executable():
    settings = _enabled_profile(
        source="service_path",
        executable="pyright-langserver",
        mode="explicit_trust_only",
    )
    verdict = assess_provider_profile(settings)
    assert verdict.classification == "not_audited"
    assert verdict.reason == "unaudited_source_or_mode"
    assert not verdict.private_launch_eligible


def test_profile_classification_tracks_options_without_exposing_arguments():
    settings = _enabled_profile(
        source="trusted_absolute",
        executable=sys.executable,
        mode="explicit_trust_only",
    )
    first = assess_provider_profile(settings)
    repeat = assess_provider_profile(settings)
    assert first == repeat
    settings.profiles["pyright"].argv = ("--danger",)
    revised = assess_provider_profile(settings)
    assert revised != first
    assert revised.reason == "unaudited_process_options"
    assert "--danger" not in repr(revised)
    assert not revised.private_launch_eligible


def test_assessment_is_inert_even_if_path_discovery_and_process_spawn_are_forbidden(
    monkeypatch,
):
    settings = _enabled_profile(
        source="trusted_absolute",
        executable="/operator/approved/pyright",
        mode="explicit_trust_only",
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("profile assessment performed forbidden I/O")

    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "resolve", forbidden)
        scoped.setattr(Path, "stat", forbidden)
        scoped.setattr("shutil.which", forbidden)
        scoped.setattr("subprocess.Popen", forbidden)
        verdict = assess_provider_profile(settings)
        assert verdict.private_launch_eligible
        assert not verdict.read_eligible
        assert verdict.source == "trusted_absolute"
        assert validate_private_profile(settings)


@pytest.mark.asyncio
async def test_manager_fails_closed_on_unapproved_options_before_source_disk_read(
    tmp_path,
):
    settings = _enabled_profile(
        source="trusted_absolute",
        executable=sys.executable,
        mode="explicit_trust_only",
        argv=("--unchecked",),
    )
    roots = RootsSettings(default_root=tmp_path, extra_roots=())
    manager = PrivateProviderManager(settings, roots)
    async with manager:
        with pytest.raises(
            ProviderManagerError, match="pyright_provider_not_authorized"
        ):
            await manager.definition(
                "relative-untrusted-input.py",
                line=1,
                column=1,
                expected_symbol="symbol",
            )
        assert manager.resident_count == manager.pending_count == 0
    assert manager.closed


def test_unknown_provider_cannot_be_injected_into_config():
    with pytest.raises(ValidationError):
        DevelopmentIntelligenceSettings(
            enabled=True,
            profiles={"injected_shell": DevelopmentProviderSettings(enabled=True)},
        )


@pytest.mark.parametrize(
    "provider",
    (
        "typescript",
        "clangd",
        "rust_analyzer",
        "marksman",
        "bash",
        "make",
        "yaml",
        "json",
    ),
)
def test_declared_trusted_other_language_server_is_not_a_launch_grant(provider):
    settings = DevelopmentIntelligenceSettings(
        enabled=True,
        profiles={
            provider: DevelopmentProviderSettings(
                enabled=True,
                source="trusted_absolute",
                executable=sys.executable,
                mode="explicit_trust_only",
            )
        },
    )
    verdict = assess_provider_profile(settings, provider)
    assert verdict.classification == "explicit_trust_only"
    assert verdict.reason == "provider_adapter_unavailable"
    assert not verdict.private_launch_eligible and not verdict.read_eligible


def test_pyright_language_profile_cannot_claim_unrelated_language():
    settings = _enabled_profile(
        source="trusted_absolute",
        executable=sys.executable,
        mode="explicit_trust_only",
        languages=("typescript",),
    )
    verdict = assess_provider_profile(settings)
    assert verdict.classification == "not_audited"
    assert verdict.reason == "unaudited_language_profile"
    assert not verdict.private_launch_eligible


def test_lowest_level_p24_owner_also_rejects_language_mismatch(tmp_path):
    settings = _enabled_profile(
        source="trusted_absolute",
        executable=sys.executable,
        mode="explicit_trust_only",
        languages=("typescript",),
    )
    project = tmp_path / "operator-granted"
    project.mkdir()
    with pytest.raises(ProviderLifecycleError, match="language_not_supported"):
        PrivatePyrightProcessOwner(settings, project, operator_allowed_roots=(project,))
