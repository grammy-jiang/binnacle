"""Public indexed-retrieval facade.

The implementation is split by responsibility while this module preserves the
existing import surface for callers and tests.
"""

from binnacle.indexed_parse import (
    PARSER_VERSION,
    SCHEMA_VERSION,
    ContextItem,
    ContextPackage,
    FreshnessDetails,
    FreshnessReport,
    IndexStats,
    ParsedFile,
    ParsedIdentifier,
    ParsedNode,
    ParsedRef,
    config_like,
    parse_config,
    parse_file,
    parse_markdown,
    parse_python,
    query_terms,
)
from binnacle.indexed_query import RelationIndexQueryMixin
from binnacle.indexed_refresh import RelationIndexRefreshMixin


class PersistentRelationIndex(RelationIndexRefreshMixin, RelationIndexQueryMixin):
    pass


__all__ = [
    "PARSER_VERSION",
    "SCHEMA_VERSION",
    "ContextItem",
    "ContextPackage",
    "FreshnessDetails",
    "FreshnessReport",
    "IndexStats",
    "ParsedFile",
    "ParsedIdentifier",
    "ParsedNode",
    "ParsedRef",
    "PersistentRelationIndex",
    "config_like",
    "parse_config",
    "parse_file",
    "parse_markdown",
    "parse_python",
    "query_terms",
]
