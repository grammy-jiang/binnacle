"""Offline JSON-only P3.6 report. Never starts a provider or follows references."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from scripts.lsp_p36_evidence import (
    EvidenceBundle,
    PolicyRequest,
)
from scripts.lsp_p36_policy import evaluate


def main(argv: list[str] | None = None) -> int:
    """Print a deterministic report; refusal is a nonzero exit, never execution."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path)
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args(argv)
    try:
        request = PolicyRequest.model_validate_json(args.request.read_bytes())
        evidence = EvidenceBundle.model_validate_json(args.evidence.read_bytes())
        decision = evaluate(request, evidence)
    except (OSError, ValidationError, ValueError):
        # Do not echo possibly private source, paths or invalid input values.
        print(
            json.dumps(
                {
                    "policy_version": "p3.6-v1",
                    "selection": "NO-GO",
                    "reason": "invalid_or_unreadable_input",
                },
                sort_keys=True,
            )
        )
        return 2
    print(decision.model_dump_json(indent=2))
    return 0 if decision.selection == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
