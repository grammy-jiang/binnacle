"""OI-01/OI-02: constrained native imports and executable Linux mechanisms."""

import pytest

from scripts import check_architecture as graph
from scripts import os_independence as guard

POLICY = graph.load_policy()


@pytest.mark.parametrize(
    "source",
    [
        "import binnacle.platform.linux.job_process\n",
        "import binnacle.platform.linux.job_process as impl\n",
        "from binnacle.platform.linux import job_process\n",
        "from binnacle.platform import linux\n",
        "from binnacle.observability import linux\n",
        '__import__("binnacle.platform.linux.job_process")\n',
        'from builtins import __import__ as load\nload("binnacle.platform.linux.job_process")\n',
        'import importlib as il\nil.import_module("binnacle.platform.linux.job_process")\n',
        'from importlib import import_module as load\nload(".linux.job_process", "binnacle.platform")\n',
        'import importlib as il\ngetattr(il, "import_module")("binnacle.platform.linux.job_process")\n',
    ],
)
def test_known_direct_and_literal_dynamic_native_imports_rejected(tmp_path, source):
    p = tmp_path / "source.py"
    p.write_text(source)
    imports = graph.imports_of(p, "binnacle.features.commands.command_execution")
    errors = guard.inspect_imports(
        {"binnacle.features.commands.command_execution": imports},
        allowed_native_owners=set(
            POLICY["os_independence"]["native_adapter_boundary_modules"]
        ),
    )
    assert errors, source


@pytest.mark.parametrize(
    "source",
    [
        'from pathlib import Path\nresult = Path("/proc/5/stat")\n',
        'from pathlib import Path\nresult = Path("/sys/fs/cgroup")\n',
        "import os\nos.killpg(123, 15)\n",
        "import os\nos.fork()\n",
        'import subprocess\nsubprocess.run(["systemctl","--user","restart","other"])\n',
        'import subprocess\nsubprocess.Popen(["journalctl", "-u", "other"])\n',
    ],
)
def test_linux_host_mechanisms_rejected_inside_pure_module(source):
    assert guard.inspect_executable_source(source, owner="binnacle.application")


@pytest.mark.parametrize(
    "source",
    [
        "from pathlib import Path\nresult=Path('/tmp/file')\n",
        "import subprocess\nsubprocess.run(['rg','needle','.'])\n",
        "import subprocess\nsubprocess.run(['git','status'])\n",
        "import os\nresult=os.environ.get('TOKEN_FILE')\n",
        'print("journalctl --user restart is a diagnostic hint")\n',
    ],
)
def test_portable_paths_and_general_subprocesses_remain_allowed(source):
    assert (
        guard.inspect_executable_source(source, owner="binnacle.features.search") == []
    )


def test_declared_native_composition_boundaries_only():
    allow = set(POLICY["os_independence"]["native_adapter_boundary_modules"])
    assert (
        guard.inspect_imports(
            {"binnacle.platform.composition": {"binnacle.platform.linux.job_process"}},
            allowed_native_owners=allow,
        )
        == []
    )
    assert guard.inspect_imports(
        {"binnacle.application": {"binnacle.platform.linux.job_process"}},
        allowed_native_owners=allow,
    )


def test_current_source_os_static_contracts():
    src = graph.ROOT / "src/binnacle"
    imports = {
        graph.module_name(path, src.parent): graph.imports_of(
            path, graph.module_name(path, src.parent)
        )
        for path in src.rglob("*.py")
    }
    assert guard.inspect_source_tree(src, policy=POLICY, imports=imports) == []
