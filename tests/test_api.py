"""Integration tests for the FastAPI endpoints using TestClient."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from rdflib import RDF, XSD, Graph, Literal, Namespace

from water_ontology.api.app import create_app
from water_ontology.api.deps import get_chain, get_engine, get_graph
from water_ontology.query.engine import QueryEngine, QueryResult
from water_ontology.query.nl_chain import ChainResult

WC = Namespace("https://w3id.org/water-contamination/")
WCD = Namespace("https://w3id.org/water-contamination/data/")

_SPARQL = (
    "PREFIX wc: <https://w3id.org/water-contamination/>\n"
    "SELECT ?name WHERE { ?f a wc:IndustrialFacility ; wc:facilityName ?name . } LIMIT 10"
)


def _graph_with_facility() -> Graph:
    g = Graph()
    fac = WCD["facility/FAC001"]
    g.add((fac, RDF.type, WC.IndustrialFacility))
    g.add((fac, WC.facilityName, Literal("Test Plant", datatype=XSD.string)))
    g.add((fac, WC.countryCode, Literal("DE", datatype=XSD.string)))
    return g


@pytest.fixture()
def graph() -> Graph:
    return _graph_with_facility()


@pytest.fixture()
def mock_chain() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def client(graph: Graph, mock_chain: MagicMock) -> TestClient:
    """
    TestClient with lifespan disabled; graph and chain injected via
    FastAPI dependency overrides so no real files or API keys are needed.
    """
    app = create_app()
    app.dependency_overrides[get_graph] = lambda: graph
    app.dependency_overrides[get_engine] = lambda: QueryEngine(graph)
    app.dependency_overrides[get_chain] = lambda: mock_chain

    # Instantiate without entering context manager so lifespan does not run.
    # Dependency overrides supply graph/chain instead.
    yield TestClient(app)


# ── /health ───────────────────────────────────────────────────────────────────

class TestHealth:
    def test_returns_ok(self, client: TestClient) -> None:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_graph_loaded_true(self, client: TestClient) -> None:
        assert client.get("/health").json()["graph_loaded"] is True

    def test_triple_count_positive(self, client: TestClient) -> None:
        assert client.get("/health").json()["triple_count"] > 0


# ── /graph/stats ──────────────────────────────────────────────────────────────

class TestGraphStats:
    def test_returns_total_triples(self, client: TestClient) -> None:
        r = client.get("/graph/stats")
        assert r.status_code == 200
        assert r.json()["total_triples"] > 0

    def test_class_counts_present(self, client: TestClient) -> None:
        counts = client.get("/graph/stats").json()["class_counts"]
        assert "IndustrialFacility" in counts
        assert counts["IndustrialFacility"] == 1

    def test_empty_classes_are_zero(self, client: TestClient) -> None:
        counts = client.get("/graph/stats").json()["class_counts"]
        assert counts["WaterBody"] == 0


# ── /query ────────────────────────────────────────────────────────────────────

class TestQueryEndpoint:
    def test_valid_sparql_returns_results(self, client: TestClient) -> None:
        r = client.post("/query", json={"sparql": _SPARQL})
        assert r.status_code == 200
        body = r.json()
        assert body["row_count"] == 1
        assert body["rows"][0]["name"] == "Test Plant"

    def test_columns_present(self, client: TestClient) -> None:
        r = client.post("/query", json={"sparql": _SPARQL})
        assert "name" in r.json()["columns"]

    def test_write_query_returns_422(self, client: TestClient) -> None:
        r = client.post("/query", json={"sparql": "DELETE WHERE { ?s ?p ?o }"})
        assert r.status_code == 422

    def test_construct_query_returns_422(self, client: TestClient) -> None:
        sparql = "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o } LIMIT 5"
        r = client.post("/query", json={"sparql": sparql})
        assert r.status_code == 422

    def test_missing_sparql_field_returns_422(self, client: TestClient) -> None:
        r = client.post("/query", json={})
        assert r.status_code == 422


# ── /ask ──────────────────────────────────────────────────────────────────────

class TestAskEndpoint:
    def _setup_chain(self, mock_chain: MagicMock) -> None:
        query_result = QueryResult(
            columns=["name"],
            rows=[{"name": "Test Plant"}],
            sparql=_SPARQL,
        )
        mock_chain.ask.return_value = ChainResult(
            question="Which facilities are in Germany?",
            sparql=_SPARQL,
            query_result=query_result,
            answer="There is one facility in Germany: Test Plant.",
        )

    def test_returns_answer(self, client: TestClient, mock_chain: MagicMock) -> None:
        self._setup_chain(mock_chain)
        r = client.post("/ask", json={"question": "Which facilities are in Germany?"})
        assert r.status_code == 200
        assert "Test Plant" in r.json()["answer"]

    def test_response_includes_sparql(self, client: TestClient, mock_chain: MagicMock) -> None:
        self._setup_chain(mock_chain)
        r = client.post("/ask", json={"question": "Which facilities are in Germany?"})
        assert "SELECT" in r.json()["sparql"]

    def test_response_includes_rows(self, client: TestClient, mock_chain: MagicMock) -> None:
        self._setup_chain(mock_chain)
        r = client.post("/ask", json={"question": "Which facilities are in Germany?"})
        assert r.json()["row_count"] == 1

    def test_short_question_returns_422(self, client: TestClient) -> None:
        r = client.post("/ask", json={"question": "Hi"})
        assert r.status_code == 422

    def test_guardrail_error_returns_422(self, client: TestClient, mock_chain: MagicMock) -> None:
        from water_ontology.query.guardrails import GuardrailError
        mock_chain.ask.side_effect = GuardrailError("blocked")
        r = client.post("/ask", json={"question": "What is the meaning of life?"})
        assert r.status_code == 422
