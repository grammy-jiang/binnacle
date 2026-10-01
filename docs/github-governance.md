# GitHub repository governance

Binnacle keeps the desired `master` branch policy in
`.github/rulesets/master.json`. The policy is intentionally compatible with
the existing gated deployment model: a candidate commit first passes CI on a
feature/ref branch, then `scripts/deploy_smoke.py deploy TARGET` fast-forwards
the production checkout and pushes the already-checked commit to `master`.

## Master ruleset

The active policy requires these GitHub Actions checks from integration
`github-actions`:

- Code quality;
- Tests / Python 3.10;
- Tests / Python 3.11;
- Tests / Python 3.12;
- Tests / Python 3.14;
- Coverage policy / Python 3.13;
- Packaging / Python 3.13.

The ruleset also blocks branch deletion and non-fast-forward updates.

It deliberately does **not** require pull requests. Binnacle's production
deployment gate is the local quiet-window/live-smoke/rollback workflow; a PR
requirement would replace rather than reinforce that model.

`strict_required_status_checks_policy` is false. The deploy preflight already
requires the target to be a fast-forward descendant of the production
checkout, while the GitHub ruleset requires that exact target commit to have
the required CI results.

Read-only check:

```bash
uv run --no-project scripts/github_governance.py check
```

Explicit ruleset reconciliation:

```bash
uv run --no-project scripts/github_governance.py apply-ruleset
```

## Compatibility probe

Before enabling the real `master` ruleset on 2026-10-01, the same rules were
applied temporarily to `refs/heads/governance-probe`.

Two pushes proved the important boundary:

1. commit `48d5a53`, whose seven CI checks had already succeeded on
   `feature/development-infrastructure-foundation`, was accepted as a direct
   branch creation/push;
2. a new fast-forward child commit with the same tree but no GitHub checks was
   rejected with `GH013` and `7 of 7 required status checks are expected`.

The probe branch and probe ruleset were then removed. This demonstrates that
the repository rule enforces "CI first, deployment push second" without forcing
the project into a pull-request-only workflow.

A second multi-ref probe exposed why deployment pushes must be atomic. With the
protected probe ref rejected, an ordinary two-ref push still advanced the
unprotected companion ref. `scripts/deploy_flow.py` therefore uses
`git push --atomic` for `master` and `proof-of-concept`, and a failed remote
push now rolls the local deployment back and re-runs the smoke.

## Dependabot

`.github/dependabot.yml` manages three ecosystems:

- `uv`: weekly, individual dependency PRs because runtime dependency changes
  remain explicit engineering decisions;
- `pre-commit`: weekly and grouped into one repository-hook PR;
- `github-actions`: weekly and grouped into one workflow-action PR.

All schedules use `Australia/Sydney` and are staggered by 15 minutes on
Wednesday morning.

Dependabot alerts and security updates are repository settings rather than
source files. Check them with the governance command above. Enable/reconcile
them explicitly with:

```bash
uv run --no-project scripts/github_governance.py enable-dependabot
```

The existing scheduled `Security` workflow remains authoritative independent
verification of the exact locked runtime and development dependency sets.
Dependabot does not replace `pip-audit`.
