"""Versioned synthetic gold cases and explicitly trusted, bounded snapshots."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

OPERATIONS = (
    "manager_definition",
    "definition",
    "references",
    "hover",
    "document_symbols",
    "workspace_symbols",
)


@dataclass(frozen=True)
class Case:
    operation: str
    file: str
    line: int
    character: int
    symbol: str
    locations: tuple[tuple[str, int, int, int, int], ...] = ()
    names: tuple[str, ...] = ()


@dataclass
class Corpus:
    files: dict[str, bytes]
    cases: tuple[Case, ...]
    kind: str
    revision: str

    def materialize(self, root: Path) -> None:
        root.mkdir()
        # Only a root marker. No Git command, inherited Git env or real Git data.
        (root / ".git").write_text("gitdir: /nonexistent/p35-disposable\n")
        for name, contents in self.files.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(contents)

    def identity(self) -> dict:
        payload = [
            (key, hashlib.sha256(value).hexdigest())
            for key, value in sorted(self.files.items())
        ]
        return {
            "kind": self.kind,
            "revision": self.revision,
            "revision_semantics": "operator_declared_git_commit_content_verified_by_manifest"
            if self.kind == "trusted_real_snapshot"
            else "versioned_generator",
            "sha256": hashlib.sha256(json.dumps(payload).encode()).hexdigest(),
            "file_count": len(self.files),
            "bytes": sum(map(len, self.files.values())),
            "gold_sha256": hashlib.sha256(repr(self.cases).encode()).hexdigest(),
        }


def synthetic(scale: str) -> Corpus:
    if scale not in ("small", "medium"):
        raise ValueError("invalid_scale")
    files = {
        "lib.py": b"def greet(name: str) -> str:\n    return name.upper()\n",
        "app.py": b"from lib import greet\nanswer = greet('Ada')\n",
        "pyrightconfig.json": b'{"include":["."],"typeCheckingMode":"standard"}\n',
    }
    if scale == "medium":
        for index in range(128):
            previous = (
                f"from unit_{index - 1:03} import value_{index - 1:03}\n"
                if index
                else ""
            )
            functions = "".join(
                f"def function_{index}_{j}(x: int) -> int:\n    return x + {j}\n\n"
                for j in range(16)
            )
            files[f"unit_{index:03}.py"] = (
                previous + f"value_{index:03} = {index}\n" + functions
            ).encode()
        files["app.py"] += b"from unit_127 import value_127\nnumber = value_127\n"
    location = (("lib.py", 0, 4, 0, 9),)
    cases = (
        Case("manager_definition", "app.py", 1, 9, "greet", location),
        Case("definition", "app.py", 1, 9, "greet", location),
        Case(
            "references",
            "app.py",
            1,
            9,
            "greet",
            location + (("app.py", 0, 16, 0, 21), ("app.py", 1, 9, 1, 14)),
        ),
        Case("hover", "app.py", 1, 9, "greet", names=("greet", "name: str")),
        Case("document_symbols", "lib.py", 0, 4, "greet", location, ("greet",)),
        Case("workspace_symbols", "lib.py", 0, 4, "greet", location, ("greet",)),
    )
    return Corpus(files, cases, f"synthetic_{scale}", "p35-python-v1")


def relative_file(value: str) -> str:
    path = Path(value)
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or ".git" in path.parts
        or "\\" in value
    ):
        raise ValueError("invalid_corpus_path")
    return value


def trusted_snapshot(root: Path, manifest: Path, authorization: Path | None) -> Corpus:
    """Read only named regular files after explicit exact-root authorization.

    This is an operator-trusted copy, NOT a sandbox or hostile path-race defense.
    Never traverse a repository or execute its configuration in place.
    """
    if authorization is None or not root.is_absolute() or authorization != root:
        raise ValueError("explicit_real_workspace_trust_required")
    root = root.resolve(strict=True)
    if manifest.stat().st_size > 262144:
        raise ValueError("manifest_too_large")
    spec = json.loads(manifest.read_text())
    if spec.get("schema") != 1 or not re.fullmatch(
        r"[0-9a-f]{40}", spec.get("revision", "")
    ):
        raise ValueError("invalid_real_manifest")
    records = spec["files"]
    if not 1 <= len(records) <= 256 or not 1 <= len(spec["cases"]) <= 32:
        raise ValueError("corpus_limit")
    files = {}
    total = 0
    for name, expected in records.items():
        relative_file(name)
        if Path(name).suffix != ".py":
            raise ValueError("real_snapshot_python_sources_only")
        source = root / name
        if any(
            part.is_symlink()
            for part in (source, *source.parents)
            if part != root.parent
        ):
            raise ValueError("corpus_symlink_denied")
        if not source.is_file() or not source.resolve().is_relative_to(root):
            raise ValueError("corpus_file_denied")
        if source.stat().st_size > 1048576:
            raise ValueError("corpus_file_too_large")
        with source.open("rb") as stream:
            data = stream.read(1048577)
        total += len(data)
        if (
            len(data) > 1048576
            or total > 8388608
            or hashlib.sha256(data).hexdigest() != expected
        ):
            raise ValueError("corpus_content_mismatch")
        files[name] = data
    cases = []
    for item in spec["cases"]:
        case = Case(
            **{
                **item,
                "locations": tuple(tuple(x) for x in item.get("locations", ())),
                "names": tuple(item.get("names", ())),
            }
        )
        if (
            case.operation not in OPERATIONS
            or case.file not in files
            or not case.symbol.isidentifier()
        ):
            raise ValueError("invalid_gold_case")
        if (
            type(case.line) is not int
            or type(case.character) is not int
            or min(case.line, case.character) < 0
        ):
            raise ValueError("invalid_gold_position")
        if (
            case.operation
            in (
                "manager_definition",
                "definition",
                "references",
                "document_symbols",
                "workspace_symbols",
            )
            and not case.locations
        ):
            raise ValueError("missing_gold_locations")
        if (
            case.operation in ("hover", "document_symbols", "workspace_symbols")
            and not case.names
        ):
            raise ValueError("missing_gold_names")
        for location in case.locations:
            if (
                len(location) != 5
                or location[0] not in files
                or any(type(n) is not int or n < 0 for n in location[1:])
            ):
                raise ValueError("invalid_gold_location")
        cases.append(case)
    if cases[0].operation != "manager_definition":
        raise ValueError("first_case_must_initialize_manager")
    # Do not ingest repository configuration, interpreter settings or plugins.
    # This is a reviewed source subset, not faithful whole-repository indexing.
    files["pyrightconfig.json"] = synthetic("small").files["pyrightconfig.json"]
    return Corpus(files, tuple(cases), "trusted_real_snapshot", spec["revision"])
