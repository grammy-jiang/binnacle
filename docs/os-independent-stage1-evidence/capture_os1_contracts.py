"""Read-only OS1 protocol and Linux process-signal characterization for review."""

import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
PROTOCOLS = (
    "process_contracts.py",
    "resource_contracts.py",
    "runtime_path_contracts.py",
    "service_lifecycle_contracts.py",
    "service_log_contracts.py",
)
output = {}
for name in PROTOCOLS:
    file = ROOT / "src/binnacle/platform/contracts" / name
    tree = ast.parse(file.read_text(encoding="utf-8"))
    output[name] = {
        "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
        "classes": {
            node.name: [
                item.name for item in node.body if isinstance(item, ast.FunctionDef)
            ]
            for node in tree.body
            if isinstance(node, ast.ClassDef)
        },
    }
process_file = ROOT / "src/binnacle/platform/linux/job_process.py"
process_tree = ast.parse(process_file.read_text(encoding="utf-8"))
backend = next(
    n
    for n in process_tree.body
    if isinstance(n, ast.ClassDef) and n.name == "LinuxProcessBackend"
)
signal = next(
    n for n in backend.body if isinstance(n, ast.FunctionDef) and n.name == "signal_job"
)
output["baseline_signal_surface"] = {
    "parameters": [p.arg for p in signal.args.args],
    "sha256": hashlib.sha256(process_file.read_bytes()).hexdigest(),
    "calls": [ast.unparse(n.func) for n in ast.walk(signal) if isinstance(n, ast.Call)],
    "limitation": "Caller checks pid/starttime earlier, but signal_job only accepts pgid and strays; check-to-signal race remains.",
    "acceptance": "OI-06 REVIEW_PENDING; native owned identity and unsafe-signal fail-closed design required",
}
path = OUT / "os1-contract-capture.json"
path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
print("captured protocols:", ", ".join(PROTOCOLS))
print("Linux stop surface:", output["baseline_signal_surface"]["parameters"])
