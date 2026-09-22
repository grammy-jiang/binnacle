"""Per-call correlation id shared by the logging middleware and the job store.

:class:`~binnacle.logging_middleware.ToolLoggingMiddleware` sets
``current_call``, client identity, and explicit argument names for one tools/call;
``jobs.start_job``
reads it so the ``job_start`` line names the call that spawned the job. The
middleware also publishes ``current_call_started`` (a monotonic timestamp) so
sync tools can measure worker-dispatch latency without changing their MCP output.
A ContextVar survives the thread hop fastmcp makes for sync tools (anyio's
``to_thread.run_sync`` copies the context) but not the reaper thread,
which only ever logs by job_id.
"""

from contextvars import ContextVar

current_call: ContextVar[str] = ContextVar("binnacle_current_call", default="-")
current_client: ContextVar[str | None] = ContextVar(
    "binnacle_current_client", default=None
)
current_argument_names: ContextVar[frozenset[str]] = ContextVar(
    "binnacle_current_argument_names", default=frozenset()
)
current_call_started: ContextVar[float | None] = ContextVar(
    "binnacle_current_call_started", default=None
)
