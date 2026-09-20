"""Unit coverage for optional tokenizer-backed telemetry."""

from binnacle import token_telemetry
from binnacle.token_telemetry import TokenCounter


class _FakeEncoder:
    def encode(self, text: str) -> list[int]:
        return list(range(len(text)))


def test_disabled_counter_never_loads(monkeypatch):
    called = False

    def load(_name: str):
        nonlocal called
        called = True
        return _FakeEncoder()

    monkeypatch.setattr(token_telemetry, "_load_encoding", load)
    counter = TokenCounter(
        enabled=False,
        encoding="o200k_base",
        client_prefixes=("openai-mcp",),
    )

    counter.prepare()

    assert counter.count(("abc",)) is None
    assert called is False


def test_loaded_counter_sums_tokenized_payload_parts(monkeypatch):
    monkeypatch.setattr(
        token_telemetry,
        "_load_encoding",
        lambda _name: _FakeEncoder(),
    )
    counter = TokenCounter(
        enabled=True,
        encoding="o200k_base",
        client_prefixes=("openai-mcp",),
    )

    counter._load()

    assert counter.count(("abc", "", "de")) == 5


def test_counter_only_applies_to_configured_client_prefixes():
    counter = TokenCounter(
        enabled=True,
        encoding="o200k_base",
        client_prefixes=("openai-mcp", "codex"),
    )

    assert counter.applies("openai-mcp(ChatGPT)") is True
    assert counter.applies("codex") is True
    assert counter.applies("claude-code") is False


def test_failed_load_disables_count_without_raising(monkeypatch, caplog):
    def fail(_name: str):
        raise RuntimeError("offline")

    monkeypatch.setattr(token_telemetry, "_load_encoding", fail)
    counter = TokenCounter(
        enabled=True,
        encoding="o200k_base",
        client_prefixes=("openai-mcp",),
    )

    counter._load()

    assert counter.count(("abc",)) is None
    assert "event=tokenizer_load_failed" in caplog.text
