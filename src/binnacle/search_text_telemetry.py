"""Low-overhead exact-search telemetry helpers.

Phase B keeps counters/timers out of the public MCP result and emits one terminal
summary per exact search. The implementation is added incrementally after the
structural seam is proven behavior-neutral.
"""
