"""Independent default-disabled Binnacle macOS maintenance profile.

This only describes an explicitly pre-created local A3 socket runtime root.
It grants no Binnacle MCP client new tools and never enables raw-log cleanup.
"""

from pathlib import Path

from pydantic import BaseModel, model_validator


class MCPMaintenanceSettings(BaseModel):
    enabled: bool = False
    control_root: Path | None = None

    @model_validator(mode="after")
    def validate_scope(self) -> "MCPMaintenanceSettings":
        if self.enabled != (self.control_root is not None):
            raise ValueError(
                "MCP maintenance requires enabled and control_root together"
            )
        return self
