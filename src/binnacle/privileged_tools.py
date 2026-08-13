"""Fail-closed bindings for reviewed but unpromoted Phase 9 Tool contracts.

The canonical manifest can bind these contracts for schema and metadata review without
making them selectable in either production catalogue. Promotion must replace this
closed boundary with an explicitly composed application use-case set.
"""

from __future__ import annotations

from typing import Never


class PrivilegedToolNotPromoted(RuntimeError):
    """A Phase 9 host-facing Tool was reached without runtime promotion."""


def _not_promoted() -> Never:
    raise PrivilegedToolNotPromoted("Phase 9 privileged Tools are not promoted")


async def privileged_prepare_v1_0(**_arguments: object) -> Never:
    _not_promoted()


async def package_inspect_v1_0(**_arguments: object) -> Never:
    _not_promoted()


async def package_install_v1_0(**_arguments: object) -> Never:
    _not_promoted()


async def binnacle_service_inspect_v1_0(**_arguments: object) -> Never:
    _not_promoted()


async def binnacle_service_restart_v1_0(**_arguments: object) -> Never:
    _not_promoted()


async def restart_preflight_v1_0(**_arguments: object) -> Never:
    _not_promoted()


async def binnacle_restart_v1_0(**_arguments: object) -> Never:
    _not_promoted()


async def binnacle_runtime_inspect_v1_0(**_arguments: object) -> Never:
    _not_promoted()


__all__ = [
    "PrivilegedToolNotPromoted",
    "binnacle_restart_v1_0",
    "binnacle_runtime_inspect_v1_0",
    "binnacle_service_inspect_v1_0",
    "binnacle_service_restart_v1_0",
    "package_inspect_v1_0",
    "package_install_v1_0",
    "privileged_prepare_v1_0",
    "restart_preflight_v1_0",
]
