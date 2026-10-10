"""OI-07: unchanged v1.0.1 client/owner RPC and spool interoperability."""

import io
import subprocess
import tarfile
from pathlib import Path

import pytest

from tests.integration.job_reload_support import reload_scenario

BASELINE_SHA = "02f4bab9bc7562668ffc41d622c4274449933768"


@pytest.fixture(scope="module")
def archived_v101_source(tmp_path_factory):
    """Use an existing immutable Git object; no network or source modifications."""
    root = Path(__file__).resolve().parents[2]
    present = subprocess.run(
        ["git", "cat-file", "-e", f"{BASELINE_SHA}^{{commit}}"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if present.returncode:
        pytest.skip("immutable v1.0.1 Git object not present in shallow clone")
    result = subprocess.run(
        ["git", "archive", "--format=tar", BASELINE_SHA, "src/binnacle"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    destination = tmp_path_factory.mktemp("binnacle-v101-immutable") / "src"
    destination.mkdir()
    with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:") as archive:
        for member in archive:
            source = Path(member.name)
            assert not source.is_absolute() and ".." not in source.parts
            # git archive includes directory entries for the requested
            # prefix; 'src/' is a parent, not a source member.
            if source.parts == ("src",):
                assert member.isdir()
                continue
            assert source.parts[:2] == ("src", "binnacle")
            target = destination.joinpath(*source.parts[1:])
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                assert member.isfile(), f"unexpected archived link: {member.name}"
                target.parent.mkdir(parents=True, exist_ok=True)
                data = archive.extractfile(member)
                assert data is not None
                target.write_bytes(data.read())
    assert (destination / "binnacle/features/commands/job_manager.py").is_file()
    return destination


@pytest.mark.parametrize(
    "manager_old", [True, False], ids=["old-owner-new-client", "new-owner-old-client"]
)
def test_bidirectional_exact_v101_rpc_and_spool_compatibility(
    tmp_path, archived_v101_source, manager_old
):
    current = Path(__file__).resolve().parents[2] / "src"
    manager = archived_v101_source if manager_old else current
    worker = current if manager_old else archived_v101_source
    observed = reload_scenario(tmp_path, manager, worker)
    assert observed["stop"]["state"] == "exited"
    assert observed["meta"]["schema_version"] == 2
    assert observed["status"]["next_cursor"].endswith(":5")
