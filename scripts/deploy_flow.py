"""Gated deploy of the production checkout (``scripts/deploy_smoke.py deploy``).

Each step either passes or stops the deploy before anything changes:

1. the checkout is a clean ``master``, and the target is a fast-forward of it;
2. every CI run for the target commit completed successfully (running runs
   are awaited up to ``--ci-timeout``);
3. a quiet moment: no tool call in the last 30 s (awaited up to
   ``--quiet-timeout``), because a reload fails the calls in flight;
4. fast-forward. When Python files under ``src/`` changed (the dev unit's
   ``--reload-dir`` watches nothing else), the dev-mode reload is awaited (a
   new ``event=config`` line), or in prod mode the unit is restarted;
5. the live smoke (``scripts/smoke_checks.py``). On success ``master`` and
   ``proof-of-concept`` are pushed atomically to origin. A failed smoke or
   failed remote push resets ``master`` to the previous commit, reloads the
   old code, and reruns the smoke to confirm the rollback.
"""

from __future__ import annotations

import json
import re

from scripts.smoke_checks import UNIT, Env, Report, last_line, smoke

QUIET_WINDOW_S = 30.0
QUIET_POLL_S = 20.0
CI_POLL_S = 30.0


def _git(env: Env, *args: str, timeout: float = 60.0) -> tuple[int, str]:
    return env.run(["git", "-C", str(env.checkout), *args], timeout)


def _repo_slug(env: Env) -> str | None:
    rc, url = _git(env, "remote", "get-url", "origin")
    m = re.search(r"github\.com[:/]([^/\s]+/[^/\s]+?)(?:\.git)?$", url.strip())
    return m.group(1) if rc == 0 and m else None


def ci_state(env: Env, sha: str) -> tuple[str, str]:
    """('success' | 'pending' | 'failed' | 'none', detail) for a commit."""
    argv = ["gh", "run", "list", "--commit", sha, "--json", "name,status,conclusion"]
    slug = _repo_slug(env)
    if slug:
        argv += ["--repo", slug]
    rc, out = env.run(argv, 60)
    if rc != 0:
        return "failed", f"gh run list failed: {last_line(out)}"
    try:
        runs = json.loads(out or "[]")
    except ValueError:
        return "failed", "unreadable gh output"
    if not runs:
        return "none", "no CI run yet"
    pending = [str(r.get("name")) for r in runs if r.get("status") != "completed"]
    if pending:
        return "pending", f"running: {', '.join(pending)}"
    bad = [
        f"{r.get('name')}={r.get('conclusion')}"
        for r in runs
        if r.get("conclusion") != "success"
    ]
    if bad:
        return "failed", "; ".join(bad)
    return "success", f"{len(runs)} run(s) succeeded"


def _wait_ci(env: Env, sha: str, timeout: float) -> tuple[bool, str]:
    deadline = env.now() + timeout
    while True:
        state, detail = ci_state(env, sha)
        if state in ("success", "failed"):
            return state == "success", detail
        if env.now() >= deadline:
            return False, f"CI not finished after {timeout:g} s ({detail})"
        env.sleep(CI_POLL_S)


def _wait_quiet(env: Env, timeout: float) -> bool:
    deadline = env.now() + timeout
    while True:
        lines = env.journal(env.now() - QUIET_WINDOW_S, None)
        if not any("event=tool_call" in ln for ln in lines):
            return True
        if env.now() >= deadline:
            return False
        env.sleep(QUIET_POLL_S)


def _prod_mode(env: Env) -> bool:
    rc, out = env.run([str(env.checkout / ".venv/bin/binnacle"), "mode", "status"], 60)
    return rc == 0 and "prod mode" in out


def _await_config(env: Env, since: float, timeout: float) -> bool:
    deadline = env.now() + timeout
    while True:
        if any("INFO: event=config" in ln for ln in env.journal(since, None)):
            return True
        if env.now() >= deadline:
            return False
        env.sleep(1)


def _server_code_changed(names: str) -> bool:
    """Did the diff touch the code the server runs? Both modes run the
    package under ``src/``; the dev unit reloads on its ``*.py`` files only."""
    return any(
        n.strip().startswith("src/") and n.strip().endswith(".py")
        for n in names.splitlines()
    )


def _make_live(
    env: Env, since: float, code_changed: bool, prod: bool, timeout: float
) -> bool:
    """Load the checkout's current code into the server; True once it runs."""
    if not code_changed:  # only *.py under src/ triggers the dev-mode reload
        return True
    if prod:
        rc, _ = env.run(["systemctl", "--user", "restart", UNIT], timeout)
        if rc != 0:
            return False
    return _await_config(env, since, timeout)


def _preflight(env: Env, target: str) -> tuple[str, str, str]:
    """(sha, previous head, problem); a problem stops the deploy."""
    _git(env, "fetch", "-q", "origin", timeout=120)
    rc, sha = _git(env, "rev-parse", "--verify", f"{target}^{{commit}}")
    if rc != 0:
        return "", "", f"unknown target {target}"
    rc_b, branch = _git(env, "rev-parse", "--abbrev-ref", "HEAD")
    rc_s, dirty = _git(env, "status", "--porcelain")
    _, prev = _git(env, "rev-parse", "HEAD")
    sha, prev = sha.strip(), prev.strip()
    if rc_b or rc_s or branch.strip() != "master" or dirty.strip():
        return sha, prev, "the checkout is not a clean master"
    if sha != prev and _git(env, "merge-base", "--is-ancestor", prev, sha)[0] != 0:
        return sha, prev, f"{sha[:7]} is not a fast-forward of {prev[:7]}"
    return sha, prev, ""


def deploy(
    env: Env,
    target: str,
    *,
    ci_timeout: float = 900.0,
    quiet_timeout: float = 1800.0,
    reload_timeout: float = 20.0,
    restart_timeout: float = 90.0,
) -> tuple[str, str]:
    """Deploy ``target``; returns (level, report text for cron-report)."""
    report = Report()

    def done(level: str, headline: str) -> tuple[str, str]:
        return level, "\n".join([f"{level.upper()}: {headline}", *report.lines()])

    sha, prev, problem = _preflight(env, target)
    if problem:
        return done("alert", f"{problem}; nothing deployed")
    if sha == prev:
        return done("ok", f"{sha[:7]} is already live; nothing to do")
    ok, detail = _wait_ci(env, sha, ci_timeout)
    report.add("ci", "ok" if ok else "alert", detail)
    if not ok:
        return done("alert", f"CI for {sha[:7]} did not pass; nothing deployed")
    if not _wait_quiet(env, quiet_timeout):
        report.add("quiet", "alert", f"tool calls did not stop for {quiet_timeout:g} s")
        return done("alert", "no quiet moment; nothing deployed")
    # --no-renames lists both sides of a move, so a module moved out of src/
    # still counts as a server change.
    rc, names = _git(env, "diff", "--name-only", "--no-renames", prev, sha)
    code_changed = rc != 0 or _server_code_changed(names)
    prod = _prod_mode(env)
    timeout = restart_timeout if prod else reload_timeout
    started = env.now()
    rc, out = _git(env, "merge", "--ff-only", sha)
    if rc != 0:
        report.add("fast-forward", "alert", last_line(out))
        return done("alert", f"fast-forward to {sha[:7]} failed; nothing deployed")
    live = _make_live(env, started, code_changed, prod, timeout)
    how = (
        ("restarted" if prod else "reloaded")
        if code_changed
        else "no server code change"
    )
    report.add(
        "reload",
        "ok" if live else "alert",
        how if live else "the new code did not load",
    )
    checked = smoke(env) if live else Report()
    report.checks.extend(checked.checks)
    if live and checked.level != "alert":
        rc, out = _git(
            env,
            "push",
            "--atomic",
            "-q",
            "origin",
            "HEAD:master",
            "HEAD:proof-of-concept",
            timeout=120,
        )
        if rc == 0:
            report.add("push", "ok", "master and proof-of-concept (atomic)")
            return done(checked.level, f"deployed {sha[:7]} (was {prev[:7]})")
        report.add("push", "alert", last_line(out) or "atomic push failed")
    failing = ", ".join(c.name for c in report.failing())
    rolled_at = env.now()
    rc, _ = _git(env, "reset", "--keep", prev)
    back = rc == 0 and _make_live(env, rolled_at, code_changed, prod, timeout)
    after = smoke(env) if back else None
    state = after.level.upper() if after else "NOT CONFIRMED"
    confirmed = after is not None and after.level != "alert"
    report.add(
        "rollback",
        "ok" if confirmed else "alert",
        f"master reset to {prev[:7]}; smoke {state}",
    )
    return done(
        "alert",
        f"deploy of {sha[:7]} failed ({failing}); rolled back to {prev[:7]} (smoke {state})",
    )
