"""Binnacle package metadata."""

from importlib.metadata import PackageNotFoundError, version

__all__ = ["distribution_version"]


def distribution_version() -> str:
    """Return the installed distribution version."""

    try:
        return version("binnacle")
    except PackageNotFoundError:
        return "0.1.0.dev0"
