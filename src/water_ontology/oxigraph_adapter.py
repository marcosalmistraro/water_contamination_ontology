"""Thin rdflib-compatible adapter over a pyoxigraph Store.

Provides the subset of the rdflib Graph API used by the Streamlit UI,
QueryEngine, NLChain, and map view — without rdflib-oxigraph (which has no
Python 3.14 wheel).
"""

from __future__ import annotations

from typing import Any, Iterator

import pyoxigraph as ox
from rdflib import BNode, Literal, URIRef
from rdflib import XSD


# ---------------------------------------------------------------------------
# Public adapter
# ---------------------------------------------------------------------------

class OxigraphAdapter:
    """Wraps a pyoxigraph Store and exposes the rdflib Graph interface."""

    def __init__(self, store: ox.Store) -> None:
        self._store = store

    def __len__(self) -> int:
        return len(self._store)

    def query(self, sparql: str, **_kwargs: Any) -> "AdaptedResult":
        result = self._store.query(sparql)
        return AdaptedResult(result)

    def subjects(
        self,
        predicate: Any = None,
        object: Any = None,  # noqa: A002
    ) -> Iterator[Any]:
        pred_ox = _to_ox(predicate) if predicate is not None else None
        obj_ox = _to_ox(object) if object is not None else None
        for quad in self._store.quads_for_pattern(None, pred_ox, obj_ox, None):
            yield _from_ox(quad.subject)


# ---------------------------------------------------------------------------
# SPARQL result wrappers
# ---------------------------------------------------------------------------

class AdaptedResult:
    """SELECT result compatible with rdflib.query.Result."""

    def __init__(self, ox_result: Any) -> None:
        self.vars: list[str] = []
        self._rows: list[AdaptedRow] = []

        if hasattr(ox_result, "variables"):
            self.vars = [v.value for v in ox_result.variables]
            self._rows = [AdaptedRow(sol, self.vars) for sol in ox_result]

    def __iter__(self) -> Iterator[AdaptedRow]:
        return iter(self._rows)

    def __len__(self) -> int:
        return len(self._rows)


class AdaptedRow:
    """One result row, accessible via row["col"] or row.get("col")."""

    def __init__(self, solution: Any, var_names: list[str]) -> None:
        self._data: dict[str, Any] = {}
        for v in var_names:
            try:
                self._data[v] = _from_ox(solution[v])
            except KeyError:
                self._data[v] = None

    def get(self, key: Any, default: Any = None) -> Any:
        return self._data.get(str(key), default)

    def __getitem__(self, key: Any) -> Any:
        return self._data[str(key)]

    def __getattr__(self, name: str) -> Any:
        try:
            return self.__dict__["_data"][name]
        except KeyError:
            raise AttributeError(name) from None


# ---------------------------------------------------------------------------
# Term conversion helpers
# ---------------------------------------------------------------------------

def _to_ox(term: Any) -> Any:
    """Convert an rdflib term to a pyoxigraph term."""
    if isinstance(term, URIRef):
        return ox.NamedNode(str(term))
    if isinstance(term, BNode):
        return ox.BlankNode(str(term))
    if isinstance(term, Literal):
        if term.language:
            return ox.Literal(str(term), language=term.language)
        if term.datatype:
            return ox.Literal(str(term), datatype=ox.NamedNode(str(term.datatype)))
        return ox.Literal(str(term))
    return None


def _from_ox(term: Any) -> Any:
    """Convert a pyoxigraph term to an rdflib term."""
    if term is None:
        return None
    if isinstance(term, ox.NamedNode):
        return URIRef(term.value)
    if isinstance(term, ox.BlankNode):
        return BNode(term.value)
    if isinstance(term, ox.Literal):
        if term.language:
            return Literal(term.value, lang=term.language)
        if term.datatype:
            return Literal(term.value, datatype=URIRef(term.datatype.value))
        return Literal(term.value)
    return None
