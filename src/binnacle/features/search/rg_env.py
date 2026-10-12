"""Config-free ripgrep invocation for the Linux list/search paths (r6 W2 X3c).

ripgrep reads extra flags from the file named by RIPGREP_CONFIG_PATH. A
config with --follow, --hidden or --no-ignore would change which objects rg
walks and opens, below the tools' own policy. Every Linux rg call therefore
passes --no-config and runs with an environment that lacks the variable;
all other variables (PATH, LANG, ...) are inherited unchanged.
"""

import os

NO_CONFIG = "--no-config"
CONFIG_ENV = "RIPGREP_CONFIG_PATH"


def rg_env() -> dict[str, str]:
    """The current environment without RIPGREP_CONFIG_PATH."""
    return {k: v for k, v in os.environ.items() if k != CONFIG_ENV}


PATTERN_HINT = "Fix the pattern, or use fixed_strings for literal text."


def rejection_message(stderr: str) -> str:
    """The rg_rejected text; a permission-only failure is not a pattern problem."""
    lines = [line for line in stderr.splitlines() if line.strip()]
    if lines and all(
        "permission denied" in line.lower() or "os error 13" in line for line in lines
    ):
        return (
            f"ripgrep could not read part of the search path: {stderr.strip()[-300:]}. "
            "Check the permissions of the path, or search a narrower path."
        )
    return f"ripgrep rejected the search: {stderr.strip()[-300:]}. {PATTERN_HINT}"
