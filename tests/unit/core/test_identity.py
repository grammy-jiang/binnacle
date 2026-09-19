from types import SimpleNamespace

from binnacle.identity import ClientIdentity


def _context(*, session_id=None, session=None, meta=None, client_params=None):
    if session is None:
        session = SimpleNamespace(client_params=client_params)
    fastmcp_context = SimpleNamespace(session_id=session_id, session=session)
    params = SimpleNamespace(meta=meta)
    return SimpleNamespace(
        fastmcp_context=fastmcp_context,
        message=SimpleNamespace(params=params),
    )


def test_modern_meta_is_returned_and_remembered_for_follow_up():
    identity = ClientIdentity()
    first = _context(
        session_id="s1",
        meta={"io.modelcontextprotocol/clientInfo": {"name": "ChatGPT"}},
    )
    follow_up = _context(session_id="s1")

    assert identity.resolve(first) == "ChatGPT"
    assert identity.resolve(follow_up) == "ChatGPT"


def test_modern_meta_overrides_legacy_session_identity():
    identity = ClientIdentity()
    legacy = SimpleNamespace(client_info=SimpleNamespace(name="Legacy Client"))
    context = _context(
        session_id="s1",
        meta={"io.modelcontextprotocol/clientInfo": {"name": "Modern Client"}},
        client_params=legacy,
    )

    assert identity.resolve(context) == "Modern Client"


def test_legacy_client_info_is_used_when_request_has_no_meta():
    identity = ClientIdentity()
    legacy = SimpleNamespace(client_info=SimpleNamespace(name="Claude"))
    context = _context(client_params=legacy)

    assert identity.resolve(context) == "Claude"


def test_missing_or_malformed_identity_returns_none():
    identity = ClientIdentity()

    assert identity.resolve(_context(meta={})) is None
    assert (
        identity.resolve(
            _context(meta={"io.modelcontextprotocol/clientInfo": "not-a-mapping"})
        )
        is None
    )
    assert identity.resolve(SimpleNamespace(fastmcp_context=None, message=None)) is None


def test_remembered_sessions_are_lru_bounded(monkeypatch):
    import binnacle.identity as identity_module

    monkeypatch.setattr(identity_module, "_REMEMBERED_SESSIONS", 2)
    identity = ClientIdentity()

    for session_id in ("one", "two", "three"):
        identity.resolve(
            _context(
                session_id=session_id,
                meta={
                    "io.modelcontextprotocol/clientInfo": {
                        "name": f"client-{session_id}"
                    }
                },
            )
        )

    assert identity.resolve(_context(session_id="one")) is None
    assert identity.resolve(_context(session_id="two")) == "client-two"
    assert identity.resolve(_context(session_id="three")) == "client-three"
