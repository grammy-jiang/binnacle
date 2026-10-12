"""F4 follow-up: server-start record clearing belongs to the active serving entry."""

from tests.unit.core.test_r6w3_e1g_serve_entry import (
    home as home,  # noqa: PLC0414 - shared test-owned fixture
)
from tests.unit.core.test_r6w3_e1g_serve_entry import (
    run_driver,
)

PROBE = """
import asyncio, json
from binnacle.startup_imports import serving_entry, serving_entry_marked
import uvicorn

async def test_only_startup(self, *args, **kwargs):
    self.started = True

uvicorn.Server.startup = test_only_startup
with serving_entry():
    import binnacle.server as server

cleared = []
server._clear_record_after_start = lambda: cleared.append("mcp")
assert not serving_entry_marked()
after_returned = list(cleared)

class OtherServer:
    started = False

asyncio.run(uvicorn.Server.startup(OtherServer()))
with serving_entry():
    class OtherWhileServing:
        started = False
        config = type("Config", (), {"app": "unrelated.asgi:app"})()

    asyncio.run(uvicorn.Server.startup(OtherWhileServing()))
    after_other = list(cleared)

    class BinnacleWhileServing:
        started = False
        config = type("Config", (), {"app": server.app})()

    asyncio.run(uvicorn.Server.startup(BinnacleWhileServing()))
    after_own = list(cleared)

print(json.dumps({
    "clears_after_serve_returned": after_returned,
    "after_other": after_other,
    "after_own": after_own,
    "clears_total": cleared,
}))
"""


def test_unrelated_uvicorn_server_after_serve_returns_cannot_clear_binnacle(home):
    outcome = run_driver(home, PROBE)
    assert outcome["clears_after_serve_returned"] == []
    assert outcome["after_other"] == []
    assert outcome["after_own"] == ["mcp"]
    assert outcome["clears_total"] == ["mcp"]
