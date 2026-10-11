"""r5 L3 (SD-50): Darwin refusals echo paths in the caller's spelling."""

import asyncio

from fastmcp import Client

from binnacle.application import create_application
from binnacle.config import RootsSettings, Settings
from binnacle.features.commands.restricted_backend import RestrictedCommandBackend
from binnacle.features.files import paths
from binnacle.platform.contracts.capability_contracts import Capability, CapabilityState
from binnacle.platform.darwin.file_access import DarwinFileAccess
from binnacle.platform.darwin.search_access import DarwinSearchAccess


def test_symlink_escape_refusal_spells_paths_as_configured(tmp_path):
    """r5 L3 (SD-50): /tmp-style aliases stay as written; no /private prefix."""
    real = tmp_path / "private-tmp"
    (real / "root").mkdir(parents=True)
    (real / "etc").mkdir()
    (real / "etc" / "hostname").write_text("secret content")
    alias = tmp_path / "tmp"
    alias.symlink_to(real, target_is_directory=True)
    root = alias / "root"
    (root / "escape").symlink_to(alias / "etc", target_is_directory=True)
    settings = Settings(roots=RootsSettings(default_root=root, extra_roots=()))
    files = DarwinFileAccess()
    access = paths.FileToolAccess(
        roots=settings.roots,
        files=files,
        search=DarwinSearchAccess(files, rg_bin="rg"),
        generation="test-caller-form",
        capability=Capability(CapabilityState.LIMITED, "test_only", "opened-object"),
    )
    app = create_application(
        settings=settings,
        token="test",
        backend=RestrictedCommandBackend(),
        file_access=access,
    )
    cases = {
        "read_file": ({"path": str(root / "escape/hostname")}, "hostname"),
        "write_file": ({"path": str(root / "escape/r4x"), "content": "x"}, "r4x"),
    }

    async def check():
        async with Client(app) as client:
            for name, (args, leaf) in cases.items():
                result = await client.call_tool(name, args, raise_on_error=False)
                assert result.is_error
                assert result.content[0].text == (
                    f"Path outside allowed roots ({root}): {alias / 'etc' / leaf}"
                )

    asyncio.run(check())
    assert not (real / "etc" / "r4x").exists()
    assert (real / "etc" / "hostname").read_text() == "secret content"
