"""Config keys that ``Settings()`` silently ignores (R6W3 R1D).

A pure helper over the parsed TOML mapping: it lists key *paths* only, never
values, and never changes how ``Settings()`` loads. ``[roots]`` is excluded:
unknown ``[roots]`` keys and roots-like top-level keys already fail start-up
(``config.roots_key_error``), so they are rejected, not ignored.
"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from difflib import get_close_matches
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic_settings import TomlConfigSettingsSource

from binnacle.config import (
    REMOVED_JOBS_KEYS,
    REMOVED_RUN_COMMAND_SECTIONS,
    REMOVED_SECTIONS,
    Settings,
    roots_like,
)

# The same cutoff config.roots_like uses for the "roots" near-miss.
NEAR_MISS_CUTOFF = 0.8

# Top-level tables that another tool owns and reads from the same config file.
# Settings() ignores them by design, so they are not reported. Add an entry
# only with its owner; an unlisted table is reported as ignored.
FOREIGN_TABLES: Mapping[str, str] = {
    "watchdog": "binnacle-watchdog (companions/watchdog/watchdog_config.py)",
}

# Removed keys, per dotted section prefix ("" is the top level). Settings()
# drops them and logs one startup warning (event=config_warning).
_REMOVED: Mapping[str, tuple[str, ...]] = {
    "": REMOVED_SECTIONS,
    "run_command": REMOVED_RUN_COMMAND_SECTIONS,
    "jobs": REMOVED_JOBS_KEYS,
}


@dataclass(frozen=True, slots=True)
class IgnoredKey:
    path: str
    removed: bool = False
    suggestion: str | None = None  # a full dotted path, like ``path``


def read_config_table(path: Path) -> dict[str, Any]:
    """Parse the TOML file as Settings() does; {} when it does not exist.

    Raises on a file that cannot be parsed (the caller reports it).
    """
    return dict(TomlConfigSettingsSource(Settings, toml_file=path).toml_data)


def _near_miss(key: str, candidates: Mapping[str, str]) -> str | None:
    """The candidate (keyed by its casefolded name) closest to ``key``."""
    hit = get_close_matches(key.casefold(), list(candidates), cutoff=NEAR_MISS_CUTOFF)
    return candidates[hit[0]] if hit else None


def _section_models(model: type[BaseModel]) -> dict[str, type[BaseModel]]:
    """Fields of ``model`` that are themselves tables with a fixed key set."""
    out: dict[str, type[BaseModel]] = {}
    for name, field in model.model_fields.items():
        annotation = field.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            out[name] = annotation
    return out


def _walk(
    data: Mapping[str, Any],
    model: type[BaseModel],
    prefix: str,
    foreign: Mapping[str, str],
) -> Iterator[IgnoredKey]:
    top = prefix == ""
    # The top level matches case-insensitively (pydantic-settings); nested
    # tables match the field name exactly.
    fields = {(name.casefold() if top else name): name for name in model.model_fields}
    foreign_names = {name.casefold(): name for name in foreign} if top else {}
    candidates = {name.casefold(): name for name in fields.values()} | foreign_names
    removed = _REMOVED.get(prefix.removesuffix("."), ())
    sections = _section_models(model)
    for raw_key, value in data.items():
        key = str(raw_key)
        path = f"{prefix}{key}"
        if key.casefold() in foreign_names:
            continue
        if key in removed:
            yield IgnoredKey(path, removed=True)
            continue
        field_name = fields.get(key.casefold() if top else key)
        if field_name is None:
            if top and roots_like(key):
                continue  # rejected at start-up (config.roots_key_error)
            near = _near_miss(key, candidates)
            yield IgnoredKey(path, suggestion=None if near is None else prefix + near)
            continue
        child = sections.get(field_name)
        if child is not None and field_name != "roots" and isinstance(value, Mapping):
            yield from _walk(value, child, f"{path}.", foreign)


def ignored_key_paths(
    data: Mapping[str, Any],
    foreign: Mapping[str, str] = FOREIGN_TABLES,
) -> list[IgnoredKey]:
    """Key paths in ``data`` that Settings() ignores, in file order."""
    return list(_walk(data, Settings, "", foreign))
