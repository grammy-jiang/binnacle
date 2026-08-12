"""Application-side client for the independent local execution supervisor."""

from binnacle.adapters.executor_ipc.client import ExecutorClient, ExecutorClientSettings

__all__ = ["ExecutorClient", "ExecutorClientSettings"]
