"""SPARQL query engine: execute a query string against the rdflib graph."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from rdflib import Graph
from rdflib.query import Result

from water_ontology.query.guardrails import validate_sparql

logger = logging.getLogger(__name__)


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[dict[str, Any]]
    sparql: str
    row_count: int = field(init=False)

    def __post_init__(self) -> None:
        self.row_count = len(self.rows)

    def is_empty(self) -> bool:
        return self.row_count == 0


class QueryEngine:
    """Execute SPARQL SELECT queries against an in-memory rdflib graph."""

    def __init__(self, graph: Graph) -> None:
        self.graph = graph

    def run(self, sparql: str) -> QueryResult:
        """Validate, execute, and return clean results for a SPARQL SELECT query."""
        # Guardrails raise on any violation before we touch the graph
        clean_sparql = validate_sparql(sparql)

        logger.debug("[QueryEngine] Executing:\n%s", clean_sparql)
        result: Result = self.graph.query(clean_sparql)

        columns = [str(v) for v in (result.vars or [])]
        rows = [
            {col: _term_value(row[col]) for col in columns}
            for row in result
        ]

        logger.debug("[QueryEngine] %d row(s) returned", len(rows))
        return QueryResult(columns=columns, rows=rows, sparql=clean_sparql)


def _term_value(term: Any) -> Any:
    """Convert an rdflib term to a plain Python value."""
    if term is None:
        return None
    # Literal with a numeric datatype → native type
    from rdflib import BNode, Literal, URIRef
    if isinstance(term, Literal):
        py = term.toPython()
        return py if not isinstance(py, Literal) else str(term)
    if isinstance(term, (URIRef, BNode)):
        return str(term)
    return str(term)
