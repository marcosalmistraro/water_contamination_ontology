"""Tests for the NL-to-SPARQL chain (LLM calls are mocked)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from rdflib import Graph, Literal, Namespace, RDF, XSD

from water_ontology.query.nl_chain import NLChain, ChainResult, _strip_fences, _format_results
from water_ontology.query.engine import QueryResult

WC = Namespace("https://w3id.org/water-contamination/")
WCD = Namespace("https://w3id.org/water-contamination/data/")

_SPARQL = (
    "PREFIX wc: <https://w3id.org/water-contamination/>\n"
    "SELECT ?name WHERE { ?f a wc:IndustrialFacility ; wc:facilityName ?name . } LIMIT 10"
)
_ANSWER = "There is one facility: Test Plant."


def _graph_with_facility() -> Graph:
    g = Graph()
    fac = WCD["facility/FAC001"]
    g.add((fac, RDF.type, WC.IndustrialFacility))
    g.add((fac, WC.facilityName, Literal("Test Plant", datatype=XSD.string)))
    return g


def _make_chain(graph: Graph) -> NLChain:
    with patch("water_ontology.query.nl_chain.NLChain._build_llm", return_value=MagicMock()):
        chain = NLChain(graph, api_key="test-key")
    return chain


class TestNLChain:
    def test_ask_returns_chain_result(self) -> None:
        graph = _graph_with_facility()
        chain = _make_chain(graph)

        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = [
            MagicMock(content=_SPARQL),   # first call: SPARQL generation
            MagicMock(content=_ANSWER),   # second call: answer generation
        ]
        chain._llm = mock_llm

        result = chain.ask("What facilities are in the graph?")
        assert isinstance(result, ChainResult)
        assert result.answer == _ANSWER
        assert result.sparql == _SPARQL

    def test_sparql_is_executed_against_graph(self) -> None:
        graph = _graph_with_facility()
        chain = _make_chain(graph)

        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = [
            MagicMock(content=_SPARQL),
            MagicMock(content=_ANSWER),
        ]
        chain._llm = mock_llm

        result = chain.ask("List all facilities.")
        assert result.query_result.row_count == 1
        assert result.query_result.rows[0]["name"] == "Test Plant"

    def test_markdown_fences_stripped_before_execution(self) -> None:
        graph = _graph_with_facility()
        chain = _make_chain(graph)

        fenced = f"```sparql\n{_SPARQL}\n```"
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = [
            MagicMock(content=fenced),
            MagicMock(content=_ANSWER),
        ]
        chain._llm = mock_llm

        result = chain.ask("List all facilities.")
        assert "```" not in result.sparql

    def test_llm_called_twice(self) -> None:
        graph = _graph_with_facility()
        chain = _make_chain(graph)

        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = [
            MagicMock(content=_SPARQL),
            MagicMock(content=_ANSWER),
        ]
        chain._llm = mock_llm

        chain.ask("How many facilities?")
        assert mock_llm.invoke.call_count == 2


class TestHelpers:
    def test_strip_fences_removes_sparql_fence(self) -> None:
        fenced = "```sparql\nSELECT ?x WHERE {}\n```"
        assert _strip_fences(fenced) == "SELECT ?x WHERE {}"

    def test_strip_fences_noop_on_plain(self) -> None:
        plain = "SELECT ?x WHERE {}"
        assert _strip_fences(plain) == plain

    def test_format_results_empty(self) -> None:
        result = QueryResult(columns=["x"], rows=[], sparql="SELECT ?x WHERE {}")
        assert _format_results(result) == "(no results)"

    def test_format_results_tabular(self) -> None:
        result = QueryResult(
            columns=["name"],
            rows=[{"name": "Test Plant"}],
            sparql="SELECT ?name WHERE {}",
        )
        text = _format_results(result)
        assert "name" in text
        assert "Test Plant" in text
