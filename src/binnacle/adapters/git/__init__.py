"""Default-disabled, typed Phase 8 Git adapter foundations."""

from binnacle.adapters.git.cli import ClosedGitExecutionPlanBuilder
from binnacle.adapters.git.config_validator import BoundedGitRepositoryProfileValidator
from binnacle.adapters.git.diff import GitDiffParseError, project_diff_result
from binnacle.adapters.git.status import GitStatusParseError, parse_porcelain_v2

__all__ = [
    "BoundedGitRepositoryProfileValidator",
    "ClosedGitExecutionPlanBuilder",
    "GitDiffParseError",
    "GitStatusParseError",
    "parse_porcelain_v2",
    "project_diff_result",
]
