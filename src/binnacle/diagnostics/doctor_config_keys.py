"""Doctor check: config keys that Settings() silently ignores (R6W3 R1D)."""

import os
from pathlib import Path

from binnacle.config import CONFIG_FILE_ENV, DEFAULT_CONFIG_FILE
from binnacle.config_unknown_keys import ignored_key_paths, read_config_table
from binnacle.doctor_contracts import Check, fail, ok, warn

GROUP = "config-keys"


def check_config_keys(path: Path | None = None) -> list[Check]:
    """WARN per ignored key path; OK when none; FAIL only if the file is unparsable.

    Reports key paths only, never values. Unknown ``[roots]`` keys fail
    start-up and are reported by the ``config`` check, not here.
    """
    cfg = path or Path(os.environ.get(CONFIG_FILE_ENV, DEFAULT_CONFIG_FILE))
    try:
        data = read_config_table(cfg)
    except Exception as e:  # noqa: BLE001 -- TOMLDecodeError, OSError
        return [fail(GROUP, f"cannot parse {cfg}: {e}", f"fix the TOML in {cfg}")]
    if not cfg.is_file():
        return [ok(GROUP, "no config file; every key is a default")]
    ignored = ignored_key_paths(data)
    if not ignored:
        return [ok(GROUP, f"every key in {cfg} is known to Settings()")]
    out: list[Check] = []
    for key in ignored:
        if key.removed:
            hint = "this key was removed; delete it from the config"
            detail = f"[{key.path}] is a removed key and is ignored"
        else:
            hint = (
                f"did you mean `{key.suggestion}`?"
                if key.suggestion
                else "check the spelling, or delete it from the config"
            )
            detail = f"`{key.path}` is not a Settings() key and is ignored"
        out.append(warn(GROUP, detail, hint))
    return out
