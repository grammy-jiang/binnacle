Python SAST policy and initial Bandit triage
============================================

The maintained Python SAST gate is Bandit ``>=1.9.4,<2`` over ``src/binnacle``.  It is
an always-on local pre-commit hook, and the canonical ``make verify`` command and the
GitHub Actions quality job both run ``pre-commit run --all-files``.  There is no result
baseline and no project-wide skipped test: every new unsuppressed finding makes the
command fail.  A suppression must name one rule at the flagged expression and have an
adjacent security rationale.

Initial triage
--------------

The initial scan contained 38 findings: 28 B101, three B103, one B105, and six B608.
Every site has the following checked-in disposition.

``B101`` -- production assertions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

All 28 assertions were replaced rather than suppressed.  Audit event payload, safe-fact,
and correlation shapes now pass explicit ``AuditIntegrityError`` checks.  Prepared and
privileged SQLite timestamps, effect-reference projections, broker restart/promotion
projections, and probe base64 input likewise use explicit fail-closed validation that is
not removed by ``python -O``.

``B103`` -- intentional permission modes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The three findings have expression-local ``# nosec B103`` dispositions:

* The audit-obligation directory is mode ``0750`` so the service group can read and
  traverse it without gaining write authority.  Marker files remain mode ``0600``.
  Unit coverage checks both modes.
* A published runtime slot root and its subdirectories are mode ``0550`` so the owner
  and runtime service group can read/traverse the immutable tree while neither receives
  write authority.  Runtime-publication coverage checks the private ``0700`` staging
  mode and the published ``0550`` mode.

``B105`` -- verdict label
~~~~~~~~~~~~~~~~~~~~~~~~

``AcceptanceVerdict.PASS`` is an evaluator result label, not a password or reusable
credential.  Only that enum assignment has ``# nosec B105``; B105 remains enabled for
the rest of the project.

``B608`` -- closed SQL construction
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

All six findings were removed by making the closed structure explicit:

* executor integrity queries are complete constant statements or selected from a
  receiver-owned mapping of the two permitted routing tables;
* executor identity lookup selects a complete statement from a receiver-owned mapping
  of its three permitted tables;
* the executor list query joins constant SQL prefix/suffix text with between one and 256
  literal ``?`` placeholders derived from the already-bounded tuple length, while every
  operation identifier remains separately bound; and
* privileged subeffect states are DB-API parameters rather than interpolated SQL.

Maintenance rule
----------------

Run the canonical gate after changing Python or a suppression:

.. code-block:: console

   make verify

Do not add global Bandit skips or a generated baseline.  Fix a finding where practical;
otherwise document the closed input or permission invariant next to a rule-specific
suppression and add or retain coverage for that invariant.
