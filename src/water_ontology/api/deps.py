"""
FastAPI dependency injection.

Graph and NLChain are loaded once at startup and shared across requests
via module-level state set by the lifespan context manager in app.py.
"""

from __future__ import annotations

from rdflib import Graph

from water_ontology.query.engine import QueryEngine
from water_ontology.query.nl_chain import NLChain

# Populated by lifespan; read by Depends callables below.
_graph: Graph | None = None
_chain: NLChain | None = None


def set_graph(graph: Graph) -> None:
    global _graph
    _graph = graph


def set_chain(chain: NLChain) -> None:
    global _chain
    _chain = chain


def get_graph() -> Graph:
    if _graph is None:
        raise RuntimeError("Graph not initialised — lifespan did not complete.")
    return _graph


def get_engine() -> QueryEngine:
    return QueryEngine(get_graph())


def get_chain() -> NLChain:
    if _chain is None:
        raise RuntimeError("NLChain not initialised — check OPENAI_API_KEY.")
    return _chain
