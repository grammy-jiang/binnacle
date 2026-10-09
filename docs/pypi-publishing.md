# Binnacle PyPI publication

## Release identity and account setup

The distribution is named **binnacle-mcp**, licensed **MIT**, and uses
Python 3.10–3.14. Public release artifacts have complete README metadata,
source links and an included LICENSE file. v1.0.1 is the first PyPI-ready
candidate; previous GitHub v1.0.0 release assets are immutable and unchanged.

PyPI and GitHub accounts are **separate**. Before the initial upload, sign in
to the authorized PyPI account and add a Pending Trusted Publisher using:

| PyPI setting | Exact value |
| --- | --- |
| Project name | binnacle-mcp |
| GitHub owner | grammy-jiang |
| Repository name | binnacle |
| Publishing workflow filename | publish-pypi.yml |
| GitHub environment | pypi |

PyPI account setup: [PyPI pending-publisher setup](https://pypi.org/manage/account/publishing/)

The GitHub pypi environment requires owner approval, accepts only v1.* tags,
and has a different trust purpose than the repository master ruleset. The
account-side pending publisher must be registered **before** publishing the
GitHub Release. A pending PyPI publisher does not reserve the package name.

Official PyPI documentation:
[Creating a PyPI project with a trusted publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
[Using a PyPI trusted publisher](https://docs.pypi.org/trusted-publishers/using-a-publisher/)
[PyPI trusted-publisher security](https://docs.pypi.org/trusted-publishers/security-model/)

## Release sequence

1. Review the fully licensed package source, version and release notes.
2. Run normal pre-commit, pre-push, exact-SHA seven required CI, Python
   compatibility and coverage gates; build both archives from sdist and
   run strict Twine metadata validation.
3. Deploy the exact reviewed commit through the ordinary Raspberry Pi guarded
   workflow. Confirm MCP HTTP, tools, job lifecycle and Live Smoke before
   any version tag. Do not restart the separate durable Job Manager unless
   it has its own approved quiet window.
4. Create an annotated immutable vX.Y.Z tag at the verified deployed SHA.
5. Verify the PyPI Pending Trusted Publisher is registered under the
   exact workflow and environment values above.
6. Publish a normal GitHub Release from the already-existing tag. This event
   starts the dedicated PyPI workflow. Its build job cannot mint an OIDC token.
7. Approve the pending deployment in GitHub's protected pypi environment.
   The publish job retrieves exact validated artifacts and obtains a short-lived
   PyPI identity through OIDC, without a stored API token.
8. Confirm PyPI project/version page, file hashes, PEP 740 attestations,
   installed-package metadata and isolated pip installation.

## Safety boundaries

- Do not publish from a PR, fork, raw branch push or manual dispatch.
- Do not bypass GitHub deployment-environment review or PyPI identity setup.
- Never change or reuse an existing release tag or uploaded package version.
  Correct mistakes with a **new version**; use GitHub deployment rollback
  independently, without rewriting history.
- Do not upload to PyPI unless the exact source SHA has seven passing required
  CI checks and has already passed the guarded local deployment.
- Do not upload non-distribution files. SHA-256 and source provenance may be
  attached to GitHub Release; the PyPI action uploads only wheel and sdist.
- The first release depends on a PyPI account owner registering its Trusted
  Publisher. GitHub repository access is not sufficient to register it.
