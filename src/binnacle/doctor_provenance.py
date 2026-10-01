"""Runtime provenance check for binnacle doctor."""

from binnacle.doctor_common import Check, ok
from binnacle.provenance import runtime_provenance


def check_provenance() -> list[Check]:
    value = runtime_provenance()
    return [
        ok(
            "version",
            f"package={value.package_version} revision={value.revision}",
        )
    ]
