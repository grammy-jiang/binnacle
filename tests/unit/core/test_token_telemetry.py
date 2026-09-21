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


def test_load_encoding_imports_tiktoken_lazily(monkeypatch):
    class FakeTiktoken:
        @staticmethod
        def get_encoding(name: str):
            assert name == "o200k_base"
            return "encoder"

    monkeypatch.setitem(__import__("sys").modules, "tiktoken", FakeTiktoken)
    assert token_telemetry._load_encoding("o200k_base") == "encoder"


def test_prepare_starts_one_daemon_loader_thread(monkeypatch):
    starts = []

    class FakeThread:
        def __init__(self, *, target, name, daemon):
            assert name == "binnacle-tokenizer"
            assert daemon is True
            self.target = target

        def start(self):
            starts.append(self.target)

    monkeypatch.setattr(token_telemetry.threading, "Thread", FakeThread)
    counter = TokenCounter(
        enabled=True,
        encoding="o200k_base",
        client_prefixes=("openai-mcp",),
    )

    counter.prepare()
    counter.prepare()

    assert starts == [counter._load]


def test_count_before_encoder_ready_starts_prepare_and_returns_none(monkeypatch):
    counter = TokenCounter(
        enabled=True,
        encoding="o200k_base",
        client_prefixes=("openai-mcp",),
    )
    calls = []
    monkeypatch.setattr(counter, "prepare", lambda: calls.append("prepare"))

    assert counter.count(("abc",)) is None
    assert calls == ["prepare"]


def test_count_failure_is_best_effort_and_logged_once(caplog):
    class FailingEncoder:
        def encode(self, _text: str):
            raise RuntimeError("bad encoding")

    counter = TokenCounter(
        enabled=True,
        encoding="o200k_base",
        client_prefixes=("openai-mcp",),
    )
    counter._encoder = FailingEncoder()

    assert counter.count(("abc",)) is None
    assert counter.count(("def",)) is None
    assert caplog.text.count("event=tokenizer_count_failed") == 1


def test_disabled_counter_never_applies_to_client():
    counter = TokenCounter(
        enabled=False,
        encoding="o200k_base",
        client_prefixes=("openai-mcp",),
    )
    assert counter.applies("openai-mcp(ChatGPT)") is False
