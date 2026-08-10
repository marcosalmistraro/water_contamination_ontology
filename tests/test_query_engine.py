"""Tests for the SPARQL query engine."""

from __future__ import annotations

import pytest
from rdflib import Graph, Literal, Namespace, RDF, XSD

from water_ontology.query.engine import QueryEngine, QueryResult, _term_value

WC = Namespace("https://w3id.org/water-contamination/")
WCD = Namespace("https://w3id.org/water-contamination/data/")


def _graph_with_facility() -> Graph:
    g = Graph()
    g.bind("wc", WC)
    g.bind("wcd", WCD)
    fac = WCD["facility/FAC001"]
    g.add((fac, RDF.type, WC.IndustrialFacility))
    g.add((fac, WC.facilityName, Literal("Test Plant", datatype=XSD.string)))
    g.add((fac, WC.countryCode, Literal("DE", datatype=XSD.string)))
    g.add((fac, WC.quantityKg, Literal(500.0, datatype=XSD.decimal)))
    return g


class TestQueryEngine:
    def test_basic_select(self) -> None:
        engine = QueryEngine(_graph_with_facility())
        sparql = """
        PREFIX wc: <https://w3id.org/water-contamination/>
        SELECT ?name WHERE {
            ?f a wc:IndustrialFacility ;
               wc:facilityName ?name .
        } LIMIT 10
        """
        result = engine.run(sparql)
        assert result.row_count == 1
        assert result.rows[0]["name"] == "Test Plant"

    def test_returns_query_result_type(self) -> None:
        engine = QueryEngine(_graph_with_facility())
        sparql = """
        PREFIX wc: <https://w3id.org/water-contamination/>
        SELECT ?f WHERE { ?f a wc:IndustrialFacility . } LIMIT 10
        """
        result = engine.run(sparql)
        assert isinstance(result, QueryResult)
        assert "f" in result.columns

    def test_empty_result_on_no_match(self) -> None:
        engine = QueryEngine(_graph_with_facility())
        sparql = """
        PREFIX wc: <https://w3id.org/water-contamination/>
        SELECT ?f WHERE { ?f a wc:WaterBody . } LIMIT 10
        """
        result = engine.run(sparql)
        assert result.is_empty()

    def test_guardrail_blocks_delete(self) -> None:
        from water_ontology.query.guardrails import GuardrailError
        engine = QueryEngine(_graph_with_facility())
        with pytest.raises(GuardrailError):
            engine.run("DELETE WHERE { ?s ?p ?o }")

    def test_guardrail_injects_limit(self) -> None:
        engine = QueryEngine(_graph_with_facility())
        sparql = """
        PREFIX wc: <https://w3id.org/water-contamination/>
        SELECT ?f WHERE { ?f a wc:IndustrialFacility . }
        """
        result = engine.run(sparql)
        assert "LIMIT" in result.sparql

    def test_numeric_literal_returned_as_float(self) -> None:
        engine = QueryEngine(_graph_with_facility())
        sparql = """
        PREFIX wc: <https://w3id.org/water-contamination/>
        SELECT ?qty WHERE {
            ?f a wc:IndustrialFacility ;
               wc:quantityKg ?qty .
        } LIMIT 10
        """
        result = engine.run(sparql)
        assert result.rows[0]["qty"] == pytest.approx(500.0)


class TestTermValue:
    def test_literal_string(self) -> None:
        from rdflib import Literal
        assert _term_value(Literal("hello")) == "hello"

    def test_literal_int(self) -> None:
        from rdflib import Literal, XSD
        assert _term_value(Literal(42, datatype=XSD.integer)) == 42

    def test_none(self) -> None:
        assert _term_value(None) is None

    def test_uri_ref(self) -> None:
        from rdflib import URIRef
        assert _term_value(URIRef("http://example.org/x")) == "http://example.org/x"
