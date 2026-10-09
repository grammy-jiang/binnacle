"""System-test isolation from the development host's physical USB inventory."""

import pytest

from binnacle.companions.watchdog.ops import cycle as watchdog_cycle


@pytest.fixture(autouse=True)
def isolate_watchdog_usb_bus(monkeypatch):
    """Cycle tests model USB observations; they must never inspect the real host.

    The hardware function itself is tested separately against a synthetic
    USB_DEVICES tree. Individual cycle tests may override this fixture's
    empty observation when they need to model an unbound adapter.
    """
    monkeypatch.setattr(watchdog_cycle, "usb_adapters_without_netdev", lambda ids: {})
