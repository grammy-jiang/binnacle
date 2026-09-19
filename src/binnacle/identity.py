"""Client identity resolution shared by the middlewares.

Who is calling arrives differently per protocol era:

- legacy sessions (2025-11-25 and older) carry ``clientInfo`` in the
  ``initialize`` handshake, readable later from the session object;
- modern requests (2026-07-28) may carry it per-request in
  ``params._meta`` -- reliably only on ``server/discover``; follow-up
  requests are bare, so a name seen in ``_meta`` is remembered per
  session and answers for the requests that follow.

One instance is shared by the logging and visibility middlewares so the
remembered sessions are a single source of truth.
"""

from collections import OrderedDict

from fastmcp.server.middleware import MiddlewareContext

CLIENT_INFO_META_KEY = "io.modelcontextprotocol/clientInfo"
_REMEMBERED_SESSIONS = 256


class ClientIdentity:
    def __init__(self) -> None:
        self._sessions: OrderedDict[object, str] = OrderedDict()

    def _session_key(self, context: MiddlewareContext) -> object | None:
        ctx = context.fastmcp_context
        if ctx is None:
            return None
        return ctx.session_id or id(ctx.session)

    def _remember(self, context: MiddlewareContext, client_name: str) -> None:
        key = self._session_key(context)
        if key is None:
            return
        self._sessions[key] = client_name
        self._sessions.move_to_end(key)
        while len(self._sessions) > _REMEMBERED_SESSIONS:
            self._sessions.popitem(last=False)

    def resolve(self, context: MiddlewareContext) -> str | None:
        """Best-known client name for this request, remembering _meta finds."""
        # Modern era: per-request _meta (present on server/discover).
        meta = getattr(getattr(context.message, "params", None), "meta", None)
        if meta:
            info = dict(meta).get(CLIENT_INFO_META_KEY)
            if isinstance(info, dict) and info.get("name"):
                name = str(info["name"])
                self._remember(context, name)
                return name
        # Legacy era: the session keeps the initialize handshake.
        ctx = context.fastmcp_context
        if ctx is not None:
            try:
                params = ctx.session.client_params
                if params is not None:
                    return params.client_info.name
            except AttributeError:
                pass
        # Modern follow-up requests: whatever an earlier _meta taught us.
        key = self._session_key(context)
        return self._sessions.get(key) if key is not None else None
