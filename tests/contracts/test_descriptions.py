"""The shipped prompt layers are the model's operating manual; this guards
their content and their division of labor (2026-09-07 review):

- tool descriptions: what the tool does and its contract, no workflow;
- server instructions: a tool map only, first 512 chars self-contained;
- the ChatGPT Project instructions (references/project-instructions.txt in
  the chatgpt-mcp-dev skill) own the workflow rules.

Phrases kept because they were measured to change behavior: search_text's
grep equivalence (grep 435 -> 0), job_status "only needed when run_command
returned a job_id" (50 blind listings), read_file's no-paging rule.
"""

import asyncio
from pathlib import Path

from fastmcp import Client

from binnacle import server

PROJECT_RULES = (
    Path(__file__).resolve().parents[2]
    / ".claude/skills/chatgpt-mcp-dev/references/project-instructions.txt"
)


def descriptions() -> dict[str, str]:
    async def run():
        async with Client(server.mcp) as c:
            return {
                t.name: " ".join((t.description or "").split())
                for t in await c.list_tools()
            }

    return asyncio.run(run())


def tokens(text: str) -> int:
    return (len(text) + 3) // 4


def test_search_text_keeps_grep_equivalence():
    d = descriptions()["search_text"].lower()
    assert "grep -rn" in d and "grep -c" in d and "grep -n" in d
    assert "prefer this over grep" in d


def test_job_status_keeps_the_only_needed_clause_and_wait_once():
    d = descriptions()["job_status"].lower()
    assert "only needed when run_command returned a job_id" in d
    assert "wait_seconds=50" in d and "instead of polling" in d


def test_run_command_keeps_not_killed_and_no_job_facts():
    d = descriptions()["run_command"].lower()
    assert "not killed" in d and "created no job" in d
    assert "several commands can go in one call" in d
    # workflow wording moved to the Project instructions
    assert "once at the end" not in d and "do not poll" not in d


def test_read_file_keeps_limit_and_no_paging():
    d = descriptions()["read_file"].lower()
    assert "24k chars" in d and "do not page through" in d and "search_text" in d
    assert "2,000 lines" not in d and "start narrow" not in d
    assert "edit_file" not in d  # hidden from ChatGPT, the only client


def test_descriptions_carry_no_workflow_and_fit_the_budget():
    d = descriptions()
    for name in (
        "read_file",
        "list_files",
        "search_text",
        "run_command",
        "job_status",
        "stop_job",
    ):
        assert "plan first" not in d[name].lower(), name
    assert (
        sum(tokens(v) for v in d.values()) < 700
    )  # was ~650 tokens of description text before the review


def test_server_instructions_are_a_map_only():
    s = server.mcp.instructions
    assert len(s) <= 512  # self-contained first block, OpenAI guidance
    for tool in (
        "list_files",
        "search_text",
        "read_file",
        "run_command",
        "job_status",
        "stop_job",
    ):
        assert tool in s
    assert "plan first" not in s.lower() and "wait_seconds" not in s


def test_project_rules_own_the_workflow():
    rules = PROJECT_RULES.read_text().lower()
    for phrase in (
        "plan first",
        "batch shell work",
        "read a file once",
        "never poll",
        "keep turns short",
        "report once",
    ):
        assert phrase in rules, phrase
    assert tokens(rules) < 260
