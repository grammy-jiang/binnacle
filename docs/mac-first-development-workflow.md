# Mac-first development through the Raspberry Pi

This is the **tested developer workflow** for future native macOS Binnacle work.
The Raspberry Pi coordinates SSH, independent Linux verification and evidence;
**the Mac performs native development and macOS testing**. It does not mean the
current Linux-only Binnacle Job Manager is supported or deployed on macOS.

The small acceptance rehearsal was executed on 2026-10-11 in
`experiment/mac-first-microtest-20261011`. It added only a parameterized
`entry_count()` regression test, not production code. See the earlier
[transport/methodology POC](darwin-investigation/native-validation/MAC-FIRST-METHOD-POC-2026-10-11.md)
for broader SSH/agent/MCP transport evidence.

## Division of responsibility

| Host | Owns | Must not assume |
| --- | --- | --- |
| MacBook Pro | Isolated native Git worktrees, local Codex/Claude (when authenticated), compiler, uv/pytest, disposable macOS MCP/probes, native logs | SSH shell is identical to interactive zsh; Linux platform stubs describe Darwin accurately |
| Raspberry Pi | Supervising ChatGPT/MCP executor, resource locks, pinned evidence, Linux-only quality gate, independent review, GitHub branch/CI tracking | Pi's local `master` always equals GitHub's `master`; a Pi-sandboxed Codex necessarily has direct SSH privileges |
| GitHub | Feature branches, immutable commits, CI checks, reviews | A successful feature branch permits merging/deploying without the separate Binnacle release gate |

Maintain **one writer per Git branch/worktree**; never rsync a mutable working
directory onto another owner's checkout. Git commits or byte-verified patches
are the exchange boundary.

## Repeatable execution recipe

### 0. Choose and freeze the baseline

Confirm the selected feature branch does not exist on GitHub, check existing
Mac worktrees, service load and the expected base commit. Get the **current**
reviewed upstream commit from GitHub; do **not** assume Pi's deployed master is
current. Preserve old Mac/RPi worktrees and check for other users' active jobs.

For a new native development project, clone the actual Git repository on Mac;
do not install Binnacle as a production Mac service during development.

### 1. Pi opens the existing trusted SSH session

Use the existing Pi SSH alias; never copy SSH private keys into a repository,
agent prompt, MCP output or Mac test fixture. Protect native sessions with the
existing cooperative locks (and a resource lock when the test is mutable or
heavy):

~~~bash
state="$HOME/.local/state/binnacle/darwin-study-parallel"
mkdir -p -m 700 "$state/locks"
flock -w 12 -s "$state/locks/mac-session.lock" \
  ssh -n -T -o BatchMode=yes -o ConnectTimeout=8 \
  -o StrictHostKeyChecking=yes mbp 'uname -sm'
~~~

For heavy/native mutable work take `mac-heavy`, `mac-launchd` or the
appropriate test-owned lock **while the SSH session and children run**; fixed
lock order is global shared then resource-specific exclusive. Set bounded
timeouts, own-resource manifests and positive cleanup criteria. Never modify
power, login, FileVault, TCC, installed launchd services or unrelated jobs.

### 2. Create a clean Mac worktree and locked environment

For an already cloned Mac repository, perform this *on Mac*, substituting a
unique ticket, branch and worktree path:

~~~bash
repo="$HOME/Projects/binnacle"
branch="feature/<ticket>"
worktree="$HOME/Projects/binnacle-worktrees/<ticket>"
git -C "$repo" fetch --no-tags origin master
git -C "$repo" worktree add -b "$branch" "$worktree" origin/master
cd "$worktree"

# Fresh SSH sessions may expose old global uv or omit Homebrew.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
uv sync --locked --group dev
export PATH="$PWD/.venv/bin:$PATH"
uv run scripts/dev.py bootstrap
uv run scripts/dev.py doctor
~~~

Pin the initial commit SHA and model/effort. The first `uv sync` creates a
project-local pinned `uv` executable; the subsequent `PATH` must prefer it.
Do not edit global shell profiles or install project packages globally.
A Git worktree requires its **own** `.venv`, not a copied Pi virtualenv.

### 3. Author on Mac with Mac-local Codex

Pi starts Mac **Codex** via its trusted SSH executor, with explicit model,
effort, Git root and sandbox. For tiny test-only work the actual POC used
`gpt-6.1-sol` with `medium` effort and `workspace-write`. For safety
critical Darwin N2/Commands work use the separately planned high/xhigh agent.

~~~bash
codex exec -m gpt-6.1-sol \
  -c 'model_reasoning_effort="medium"' \
  -c 'approval_policy="never"' \
  -s workspace-write \
  -C "$worktree" --json \
  'Make only the authorized scoped change and run focused tests'
~~~

Inside the agent's `zsh -lc` command shell the incoming SSH `PATH` may be
reset. Instruct agent commands to use `./.venv/bin/uv` or a **command-local**
`PATH="$PWD/.venv/bin:$HOME/.local/bin:/opt/homebrew/bin:$PATH"`. A
sandbox-restricted cache may require a private, positively owned
`UV_CACHE_DIR`. Do not turn off the sandbox or globally loosen permissions
to hide an error. Record job_id/session, source scope and logs; do not interpret
a started SSH process as completed work.

Claude Code was **not** a proven alternative in the earlier POC: its installed
CLI failed a live call because OAuth refresh had expired. Reauthenticate by
the normal interactive supported mechanism before scheduling Claude authors.

### 4. Test and review on Mac; distinguish native vs Linux gates

Run the **small affected** pytest module first and inspect the diff:

~~~bash
./.venv/bin/uv run --no-sync python -m pytest -q tests/unit/core/<case>.py
git diff --check
git diff --stat
git status --short
~~~

Run normal pre-commit on the changed files during iteration. Its visible
`mypy-linux` and `mypy-darwin` hooks both check `src/binnacle tests scripts`
using the existing locked uv/mypy environment on either host. Each retains
the Python-file trigger and full source scope of the original hook. A
changed-files run therefore still checks the whole source set for both targets.
For standalone reproduction:

~~~bash
export PATH="$PWD/.venv/bin:$HOME/.local/bin:/opt/homebrew/bin:$PATH"
./.venv/bin/uv run --no-sync mypy --platform linux --cache-dir .mypy_cache/linux src/binnacle tests scripts
./.venv/bin/uv run --no-sync mypy --platform darwin --cache-dir .mypy_cache/darwin src/binnacle tests scripts
~~~

The 2026-10-11 microtask's original Mac hook failed with two `attr-defined`
errors: `signal.pidfd_send_signal` in `platform/linux/job_identity.py` and
`socket.SO_BINDTODEVICE` in `companions/watchdog/uplink.py`. Linux-targeted
mypy passed. The bounded infrastructure fix replaces these direct attribute
accesses with typed capability lookups. Missing pidfd support still refuses
safe-signal acquisition; losing the sender at delivery raises
`JobSignalDeliveryError`. Verified descriptor ownership, descendant ordering
and per-target signal errors are preserved, with no numeric-PID fallback.
Missing socket device binding raises `ProbeUnavailable`, so the watchdog
reports unknown rather than a failed route. Synthetic tests cover missing
capabilities and positive Linux behavior without using real pidfds or device
socket options on the Mac.

Both targets are required; neither target grants runtime macOS support.
The hooks use separate `.mypy_cache/linux` and `.mypy_cache/darwin` directories
to avoid repeatedly invalidating a shared cache when switching targets. This
adds a second complete type-check invocation, including its cold-cache cost.
On the Mac-native fix worktree (2026-10-11, Python 3.13, 421 source files),
standalone mypy took 2.92 s for Linux and 2.84 s for Darwin with fresh target
caches; immediate warm repeats took 0.16 s each. These are local observations,
not Pi or CI performance guarantees, and exclude pre-commit startup overhead.

**Do not skip/disable or weaken the canonical hook to get a green commit.**
Hand over the **byte-verified patch** for independent source-bound review and
the Pi's final gates before integration. A Mac-only test pass does not establish
Linux runtime correctness, just as a Pi Linux pass does not establish native
macOS behavior. Full-suite, coverage, compatibility and deployment gates remain
unchanged; avoid repeating full pytest/tox during bounded source iteration.

### 5. Transfer the Mac-authored patch and integrate on Pi

At an exact pinned parent revision:

~~~bash
git -C "$worktree" diff --binary -- tests/unit/core/<case>.py \
  > "$private_mac_fixture/author.patch"
shasum -a 256 "$private_mac_fixture/author.patch"
# Pi: rsync over trusted SSH into a private Pi fixture (do not overwrite)
rsync -a -e 'ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes' \
  mbp:Projects/<owned-dir>/author.patch "$private_pi_fixture/author.patch"
sha256sum "$private_pi_fixture/author.patch"

# Pi: independent checkout of the same pinned upstream base.
git clone https://github.com/grammy-jiang/binnacle.git "$pi_integration"
git -C "$pi_integration" switch -c "$branch"
git -C "$pi_integration" apply --check "$private_pi_fixture/author.patch"
git -C "$pi_integration" apply "$private_pi_fixture/author.patch"
~~~

Verify the *whole patch SHA* and original Git base SHA, not just filenames.
Run the same focused test on Linux; check the exact file scope. Bootstrap
the Pi checkout with `uv run scripts/dev.py bootstrap`, then
`git add` and **ordinary `git commit`** so all project hooks execute
without overrides. The result is a normal Git commit. Do not edit product
source in parallel from Pi.

### 6. Verify the commit, publish only a feature branch, and retrieve on Mac

After Linux hooks and read-only independent source review:

~~~bash
# Pi isolated integration checkout only; normal pre-push hook must run.
git push origin "$branch"

# Pi watches the exact HEAD SHA, CI run and required checks.
gh run list -R grammy-jiang/binnacle --branch "$branch" --workflow ci.yml
gh api "repos/grammy-jiang/binnacle/commits/<exact-sha>/check-runs"
~~~

Push **one** converged candidate rather than rerunning full suites after
every change. A pull request is optional for this repository; if used,
remember that `pull_request` and `push` can each trigger CI.

Then fetch this exact branch on Mac and compare the **committed** test file
against Mac's recorded changed file. Close/clean only known test-owned
fixtures. Never reset another owner's worktree or delete a lock blindly.

**A feature-branch push is not a deployment.** No fast-forward of protected
master, no release, no PyPI publication, no systemd restart and no production
Mac launchd installation without later separately authorized gates.

## Recorded microtask evidence, 2026-10-11

- Selected change: five `search_text_budget.entry_count()` edge cases
  (missing, `None`, string, dictionary, two-entry list); **one test file,
  15 lines added, no product source change**.
- Mac source base: GitHub `master` at
  `d61761356ee0fce8ea6d73b0c3043b4881c5645e`; isolated native
  worktree `experiment/mac-first-microtest-20261011`.
- Mac environment: `uv==0.12.24` from the project virtualenv,
  development doctor **9/9**, prior baseline **1 passed**, Codex focused
  pytest **6 passed**, Mac Linux-targeted mypy **421 files / 0 issues**.
- Mac standard mypy hook: **failed** on two Linux-only API attributes under
  Darwin typeshed. This was the **observed local hook compatibility gap**
  addressed by the dual-platform policy above, not a new test regression or
  release exception. The original failure remains part of the microtask record.
- Pi received the Mac-authored patch via SSH/rsync. Both SHA-256 values were
  `5ee28387f393c5c439902fd6532e6f890369b1d6b6bdfe34aed2c08ce0b2fa8b`;
  independent Pi clone confirmed **byte-for-byte equality**.
- Pi isolated integration base pinned to the same GitHub SHA; focused
  pytest **6 passed** and **unchanged Linux pre-commit hooks passed**.
  Commit: `300d4bae0974431b0ae1b14a061d6422c760215a`.
- The prior Mac-first POC separately proved Pi→Mac SSH, Git bundle, native
  Codex read/write and transient MCP stdio over SSH. **This microtask does not
  install or verify a real Binnacle Darwin Job Manager**.
- Record CI outcomes independently against the exact published candidate SHA;
  do not infer green CI from local tests.

## Recovery and boundaries

- Failed SSH/auth: stop, keep the owned job ID/lease, inspect the actual
  returned error, do not disable SSH host key checking or change global
  credentials. Pi sandboxed Codex direct SSH and its never-approval MCP path
  were **not** viable in the previous POC; use the Pi supervisor's authorized
  trusted SSH executor launching **Mac-local Codex**.
- Mac command denied by sandbox: distinguish executable/temporary cache,
  PATH/uv and actual code failures. Fix a test-owned scope or return the
  result as blocked; no privilege escalation for convenience.
- Commit-hook failure: do not weaken it; run a scoped diagnostic, then move
  same Git patch to Pi and run full unmodified hooks there.
- CI failure: retrieve failing job and related logs, rerun only the failed
  scope on the correct platform. Preserve SHA-bound evidence; do not claim
  accepted code or deploy it.
- Worker failure/timeout: inspect tracked branch, worktree, exact commit,
  log and owned child processes; resume that worker's durable session when
  available. No duplicate simultaneous source owners or destructive cleanup.
- Native test leases: require positive ownership and cleanup of process,
  launchd label, socket and scratch root before releasing a lock or claiming
  completion. The harmless entry-count microtask did not run native Binnacle
  Commands or manipulate system services.
