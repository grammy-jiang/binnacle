"""Runtime provenance check for binnacle doctor."""

from binnacle.doctor_contracts import Check, ok
from binnacle.provenance import Provenance, runtime_provenance


def check_provenance(value: Provenance | None = None) -> list[Check]:
    value = runtime_provenance() if value is None else value
    return [
        ok(
            "version",
            f"package={value.package_version} revision={value.revision}",
        )
    ]
