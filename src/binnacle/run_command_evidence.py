"""Compatibility facade for Commands automatic-background evidence."""

from binnacle.features.commands import run_command_evidence as _impl

EVIDENCE_DIR = _impl.EVIDENCE_DIR
os = _impl.os
record_auto_match = _impl.record_auto_match
load_evidence = _impl.load_evidence

__all__ = ["EVIDENCE_DIR", "load_evidence", "record_auto_match"]
