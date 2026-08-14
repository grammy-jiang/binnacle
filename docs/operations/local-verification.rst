Local repository verification
=============================

``make verify`` is the canonical clean-checkout and pre-push verification command.
Install ``uv`` and run it from the repository root:

.. code-block:: console

   make verify

The target uses the locked development environment and stops at the first failing
command.  It runs the pytest and branch-coverage suite on Python 3.11, 3.12, and 3.13,
then runs the complete quality profile and every pre-commit hook.  The quality profile
contains Ruff lint and formatting, strict MyPy, Import Linter, ``pip-audit``, recursive
RST validation, generated-registry and contract/schema checks, operational CLI smoke
checks, and the isolated Phase 04, 07, 08, and 09 verifier workflows.

The narrower ``make verify-python PYTHON=3.11`` and ``make verify-quality`` targets are
diagnostic entry points, not substitutes for the complete pre-push command.  The attested
GitHub Actions workflow retains its independent job layout; the checked-in
``tests/unit/test_repository_verification.py`` contract compares every remote gate with
the corresponding ``tox`` command and prevents drift.  A non-zero exit identifies the
failed ``tox`` environment or pre-commit command; fix that failure and rerun
``make verify`` before publishing.
