"""Device identity port."""

from typing import Protocol

from binnacle.domain.system import DeviceIdentity


class DeviceIdentityProvider(Protocol):
    def get_device_identity(self) -> DeviceIdentity: ...
