"""E2 session-route modules for the portable-import contract (lab only).

Kept separate so the frozen contract test stays under the module-size limit.
"""

SESSION_MODULES = {
    "session_binding.py",
    "session_emission.py",
    "session_lab.py",
    "session_route.py",
    "session_serving.py",
    "session_snapshot.py",
    "session_fence.py",
}
SESSION_LOCAL_FROM_IMPORTS: dict[str, dict[str, set[str]]] = {
    "session_binding.py": {
        "models": {"JobRef", "OutputSnapshot", "VerifiedPrincipal", "VerifiedRunGrant"},
        "session_route": {"KeyDigest"},
    },
    "session_emission.py": {
        "hint_policy": {"MAX_HINT_JOBS"},
        "models": {
            "AuthorityDecision",
            "JobRef",
            "ReceiptState",
            "Scope",
            "Success",
            "VerifiedRunGrant",
        },
        "session_binding": {
            "ABORT",
            "AllocationEntry",
            "EMIT",
            "KeyBinding",
            "LabFailure",
            "LabTx",
            "RESERVE",
            "RESET",
        },
        "session_lab": {"SessionLab"},
        "session_route": {"KeyDigest", "RouteOutcome", "SessionRoute"},
    },
    "session_lab.py": {
        "grants": {"SyntheticAuthority", "TrustedClock"},
        "models": {
            "AuthorityDecision",
            "Failure",
            "JobRef",
            "Observation",
            "ObservationState",
            "Result",
            "Scope",
            "Success",
            "VerifiedPrincipal",
            "VerifiedRunGrant",
        },
        "ports": {"ReceiptQueryPort"},
        "receipt_schema": {"Limits"},
        "session_binding": {
            "AllocationEntry",
            "KeyBinding",
            "LabFailure",
            "LabLedger",
            "SessionBindingTable",
            "prepare_layout",
        },
        "session_fence": {"FenceSet"},
        "session_route": {
            "ISSUER_SESSION_V1",
            "KeyDigest",
            "RouteOutcome",
            "RouteStatus",
            "SessionKeyer",
        },
        "session_snapshot": {
            "AllocationSnapshot",
            "FrozenTemplate",
            "MemoryPayload",
            "build_snapshot",
            "output_snapshot",
            "valid_slot",
        },
        "snapshots": {"SnapshotMemory", "SnapshotStore", "TrustedCatalog"},
    },
    "session_serving.py": {
        "models": {"AuthorityDecision", "Scope", "Success", "VerifiedRunGrant"},
        "session_binding": {"AllocationEntry", "KeyBinding", "LabFailure"},
        "session_lab": {"LabError", "SessionLab"},
        "session_route": {"KeyDigest", "RouteOutcome"},
        "session_snapshot": {"echo_matches", "logical_page", "valid_slot"},
    },
    "session_snapshot.py": {
        "identifiers": {"canonical_hex", "require"},
        "models": {
            "BoundaryError",
            "ErrorCode",
            "Failure",
            "JobRef",
            "MAX_SNAPSHOT_BYTES",
            "OutputSnapshot",
            "Result",
            "SourceKind",
            "Success",
            "TerminalKind",
            "TerminalOutcome",
        },
    },
    "session_route.py": {
        "identifiers": {"canonical_hex", "require"},
        "models": {"JobRef", "PrincipalClaims", "VerifiedRunGrant"},
    },
}
