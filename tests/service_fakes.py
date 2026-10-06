"""Small managed-service fakes shared by G4 tests."""

from dataclasses import dataclass, field

from binnacle.service_lifecycle_contracts import ManagedServiceStatus


@dataclass
class FakeServiceInspector:
    statuses: dict[str, ManagedServiceStatus] = field(default_factory=dict)
    paths: dict[str, str | None] = field(default_factory=dict)
    environment_matches: dict[tuple[str, str, str], bool | None] = field(
        default_factory=dict
    )
    rss: dict[str, float | None] = field(default_factory=dict)
    started: dict[str, float | None] = field(default_factory=dict)

    def status(self, service: str) -> ManagedServiceStatus:
        return self.statuses.get(service, ManagedServiceStatus("inactive"))

    def main_process_path(self, service: str) -> str | None:
        return self.paths.get(service)

    def main_process_has_environment(
        self, service: str, name: str, value: str
    ) -> bool | None:
        return self.environment_matches.get((service, name, value))

    def rss_kb(self, service: str) -> float | None:
        return self.rss.get(service)

    def started_at_epoch(self, service: str) -> float | None:
        return self.started.get(service)
