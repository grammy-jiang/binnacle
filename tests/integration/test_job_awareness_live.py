"""Production Job Awareness hints over native streamable HTTP.

Every call uses the strict FastMCP client, so each structured result (with or
without the hint) is validated against the output schema that the same
client listed. The application is the real ``create_application`` tree with
an in-memory job backend (``Jobs``); no real process or job store is used.
"""

import asyncio
import logging

import pytest

from binnacle.mcp.job_awareness_route import RAW_VALUE
from tests.integration.job_awareness_live_support import (
    CHATGPT,
    Jobs,
    application,
    conversation,
    hint_of,
    http_client,
    message,
    payloads,
)

HINT = "job_awareness_hint"
CHATGPT_TOOLS = [
    "read_file",
    "list_files",
    "search_text",
    "run_command",
    "job_status",
    "stop_job",
]


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def root(tmp_path):
    (tmp_path / "note.txt").write_text("alpha\nbeta\n")
    return tmp_path


@pytest.fixture
def ja_log(caplog):
    caplog.set_level(logging.INFO, logger="binnacle.job_awareness")
    return caplog


def ja_lines(caplog) -> list[str]:
    return [
        r.getMessage() for r in caplog.records if r.name == "binnacle.job_awareness"
    ]


async def start(client, root, meta) -> str:
    result = await client.call_tool(
        "run_command",
        {"command": "make all", "workdir": str(root), "background": True},
        meta=meta,
    )
    assert result.structured_content["state"] == "running"
    return result.structured_content["job_id"]


async def browse(client, root, meta):
    return await client.call_tool("list_files", {"path": str(root)}, meta=meta)


# ------------------------------------------------------------ default off


async def _golden_session(app, jobs, root, raw):
    headers, meta = conversation("golden")
    async with http_client(app, headers=headers, raw=raw) as client:
        await client.list_tools()
        job = await start(client, root, meta)
        jobs.finish(job, 2)
        await browse(client, root, meta)
        await client.call_tool("read_file", {"path": str(root / "note.txt")}, meta=meta)
        await client.call_tool("job_status", {"job_id": job}, meta=meta)
        await client.call_tool("job_status", {}, meta=meta)


def _golden(root, enabled):
    app, jobs = application(root, enabled=enabled)
    raw: list[bytes] = []
    run(_golden_session(app, jobs, root, raw))
    return payloads(raw), app


def test_default_off_is_byte_identical_to_an_absent_setting(root):
    absent, absent_app = _golden(root, None)
    off, off_app = _golden(root, False)
    assert off == absent
    assert len(off) >= 6
    assert all(HINT.encode() not in payload for payload in off)
    assert [type(m) for m in off_app.middleware] == [
        type(m) for m in absent_app.middleware
    ]
    assert not any("job_awareness" in type(m).__module__ for m in off_app.middleware)
    on, _ = _golden(root, True)  # negative control: the golden sees a change
    assert on != absent
    assert any(HINT.encode() in payload for payload in on)


def test_default_settings_keep_hints_off(root):
    app, _ = application(root, enabled=None)
    assert not any("job_awareness" in type(m).__module__ for m in app.middleware)


# ------------------------------------------------------------ tools/list


async def _schemas(app, name):
    headers, _ = conversation("list")
    async with http_client(app, name=name, headers=headers) as client:
        return {t.name: t.output_schema for t in await client.list_tools()}


def test_enabled_list_declares_the_optional_field_for_chatgpt_only(root):
    on, _ = application(root, enabled=True)
    off, _ = application(root, enabled=False)
    chatgpt = run(_schemas(on, CHATGPT))
    assert list(chatgpt) == CHATGPT_TOOLS
    baseline = run(_schemas(off, CHATGPT))
    for name, schema in chatgpt.items():
        field = schema["properties"].pop(HINT)
        assert field == {"type": "string", "maxLength": 512}
        assert HINT not in schema.get("required", [])
        assert schema == baseline[name]  # nothing else changed
    for other in ("openai-mcp(Codex)", "claude-code", "codex"):
        assert run(_schemas(on, other)) == run(_schemas(off, other))


# ------------------------------------------------------------ emission


def test_hint_reaches_the_starting_conversation_once(root, ja_log):
    app, jobs = application(root, enabled=True)
    headers, meta = conversation("alpha")

    async def go():
        async with http_client(app, headers=headers) as client:
            job = await start(client, root, meta)
            assert hint_of(await browse(client, root, meta)) is None  # running
            jobs.finish(job, 3)
            first = await browse(client, root, meta)
            second = await browse(client, root, meta)
            return job, first, second

    job, first, second = run(go())
    text = hint_of(first)
    assert text.startswith("[Binnacle job reminder]")
    assert f"Background job {job}" in text and "exit_code 3" in text
    assert len(text.encode()) <= 512
    assert hint_of(second) is None
    lines = ja_lines(ja_log)
    assert any(f"event=ja_bind outcome=bound job={job}" in line for line in lines)
    assert sum("event=ja_hint outcome=emitted" in line for line in lines) == 1


def test_two_conversations_never_cross(root, ja_log):
    app, jobs = application(root, enabled=True)
    headers_a, meta_a = conversation("alpha")
    headers_b, meta_b = conversation("bravo")

    async def go():
        async with http_client(app, headers=headers_a) as a:
            job = await start(a, root, meta_a)
        jobs.finish(job, 0)
        async with http_client(app, headers=headers_b) as b:
            b_first = await browse(b, root, meta_b)
            b_status = await b.call_tool("job_status", {}, meta=meta_b)
        async with http_client(app, headers=headers_a) as a:
            a_first = await browse(a, root, meta_a)
        async with http_client(app, headers=headers_b) as b:
            b_late = await browse(b, root, meta_b)
        return job, b_first, b_status, a_first, b_late

    job, b_first, b_status, a_first, b_late = run(go())
    assert hint_of(b_first) is None and hint_of(b_status) is None
    assert job in hint_of(a_first)
    assert hint_of(b_late) is None
    keys = {
        line.split("ja_key=")[1]
        for line in ja_lines(ja_log)
        if "event=ja_bind" in line or "event=ja_hint" in line
    }
    assert len(keys) == 1  # only conversation A ever bound or received


@pytest.mark.parametrize(
    "name", ["openai-mcp(Codex)", "claude-code", "codex", "unknown-client"]
)
def test_non_chatgpt_clients_get_no_hint_and_no_binding(root, ja_log, name):
    app, jobs = application(root, enabled=True)
    headers, meta = conversation("alpha")

    async def go():
        async with http_client(app, name=name, headers=headers) as client:
            job = await start(client, root, meta)
            jobs.finish(job)
            return await browse(client, root, meta)

    assert hint_of(run(go())) is None
    assert ja_lines(ja_log) == [
        "event=job_awareness_config hints_enabled=true clients=2 carrier=struct"
    ]


def _mismatch():
    headers, _ = conversation("alpha")
    _, other = conversation("bravo")
    return headers, other


@pytest.mark.parametrize(
    ("label", "build"),
    [
        ("no_headers", lambda: ({}, conversation("alpha")[1])),
        ("no_meta", lambda: (conversation("alpha")[0], None)),
        ("mismatch", _mismatch),
        (
            "malformed",
            lambda: (
                {"x-openai-session": "v1/short", "x-openai-subject": "v1/short"},
                {"openai/session": "v1/short", "openai/subject": "v1/short"},
            ),
        ),
    ],
)
def test_ambiguous_route_fails_closed(root, ja_log, label, build):
    app, jobs = application(root, enabled=True)
    headers, meta = build()

    async def go():
        async with http_client(app, headers=headers) as client:
            first = await client.call_tool(
                "run_command",
                {"command": "make", "workdir": str(root), "background": True},
                meta=meta,
            )
            jobs.finish(first.structured_content["job_id"])
            return await browse(client, root, meta)

    assert hint_of(run(go())) is None
    lines = ja_lines(ja_log)
    assert not any("event=ja_bind" in line for line in lines)
    assert any("event=ja_route status=" in line for line in lines)


def test_reading_or_stopping_the_job_acknowledges_it(root, ja_log):
    app, jobs = application(root, enabled=True)
    headers, meta = conversation("alpha")

    async def go():
        async with http_client(app, headers=headers) as client:
            read_job = await start(client, root, meta)
            stop_job = await start(client, root, meta)
            jobs.finish(read_job, 0)
            status = await client.call_tool(
                "job_status", {"job_id": read_job}, meta=meta
            )
            await client.call_tool("stop_job", {"job_id": stop_job}, meta=meta)
            return status, await browse(client, root, meta)

    status, later = run(go())
    assert hint_of(status) is None and hint_of(later) is None
    assert sum("event=ja_ack" in line for line in ja_lines(ja_log)) == 2


def test_two_finished_jobs_share_one_hint_on_any_tool(root):
    app, jobs = application(root, enabled=True)
    headers, meta = conversation("alpha")

    async def go():
        async with http_client(app, headers=headers) as client:
            first = await start(client, root, meta)
            second = await start(client, root, meta)
            third = await start(client, root, meta)
            for job in (first, second, third):
                jobs.finish(job, 1)
            listing = await client.call_tool("job_status", {}, meta=meta)
            later = await client.call_tool(
                "read_file", {"path": str(root / "note.txt")}, meta=meta
            )
            last = await browse(client, root, meta)
            return (first, second, third), listing, later, last

    (first, second, third), listing, later, last = run(go())
    assert first in hint_of(listing) and second in hint_of(listing)
    assert third not in hint_of(listing)
    assert third in hint_of(later)
    assert hint_of(last) is None


def test_unreadable_job_state_suppresses_then_recovers(root, ja_log):
    app, jobs = application(root, enabled=True)
    headers, meta = conversation("alpha")

    async def go():
        async with http_client(app, headers=headers) as client:
            job = await start(client, root, meta)
            jobs.finish(job)
            jobs.fail_reads = True
            failed = await browse(client, root, meta)
            jobs.fail_reads = False
            return job, failed, await browse(client, root, meta)

    job, failed, recovered = run(go())
    assert hint_of(failed) is None
    assert job in hint_of(recovered)


def test_a_restart_forgets_every_binding(root):
    jobs = Jobs()
    first_app, _ = application(root, enabled=True, backend=jobs)
    second_app, _ = application(root, enabled=True, backend=jobs)
    headers, meta = conversation("alpha")

    async def go():
        async with http_client(first_app, headers=headers) as client:
            job = await start(client, root, meta)
        jobs.finish(job)
        async with http_client(second_app, headers=headers) as client:
            return await browse(client, root, meta)

    assert hint_of(run(go())) is None


def test_journal_lines_carry_no_raw_platform_value(root, ja_log):
    app, jobs = application(root, enabled=True)
    headers, meta = conversation("alpha")

    async def go():
        async with http_client(app, headers=headers) as client:
            job = await start(client, root, meta)
            jobs.finish(job)
            await browse(client, root, meta)
        async with http_client(app, headers={}) as client:
            await browse(client, root, None)

    run(go())
    text = "\n".join(r.getMessage() for r in ja_log.records)
    assert "event=ja_hint outcome=emitted" in text
    assert RAW_VALUE.search(text) is None
    for value in (*headers.values(), *meta.values()):
        assert value not in text


def test_hinted_wire_result_is_the_structured_field_and_text_is_unchanged(root):
    app, jobs = application(root, enabled=True)
    headers, meta = conversation("alpha")
    raw: list[bytes] = []

    async def go():
        async with http_client(app, headers=headers, raw=raw) as client:
            job = await start(client, root, meta)
            jobs.finish(job)
            await browse(client, root, meta)

    run(go())
    results = [
        message(p)["result"]
        for p in payloads(raw)
        if "content" in message(p).get("result", {})
    ]
    hinted = results[-1]
    assert HINT in hinted["structuredContent"]
    assert all(HINT not in block["text"] for block in hinted["content"])
