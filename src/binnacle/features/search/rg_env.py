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
