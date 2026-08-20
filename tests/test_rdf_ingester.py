"""Unit tests for INSPIRE/EnvThes RDF ingester."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from rdflib import RDF, Graph, URIRef

from water_ontology.ingesters.rdf_ingester import RdfIngester

WCD = "https://w3id.org/water-contamination/data/"
WC = "https://w3id.org/water-contamination/"
EXT = "http://vocab.example.org/"


def _build_external_graph() -> tuple[Graph, str]:
    """Build a minimal SKOS graph in Turtle and return (graph, turtle_str)."""
    ttl = f"""
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix ex:   <{EXT}> .

ex:pollutant_001 a skos:Concept ;
    skos:prefLabel "arsenic pollutant"@en ;
    skos:definition "Arsenic as an environmental pollutant"@en .

ex:waterbody_001 a skos:Concept ;
    skos:prefLabel "river water body"@en .

ex:other_001 a skos:Concept ;
    skos:prefLabel "some other concept"@en .
"""
    return Graph().parse(data=ttl, format="turtle"), ttl


def _make_ingester(empty_graph):  # type: ignore[no-untyped-def]
    cfg = MagicMock()
    cfg.url = "http://example.com/envthes.ttl"
    cfg.local_file = None
    ingester = RdfIngester(empty_graph, cfg, raw_dir=MagicMock(), fmt="turtle")
    return ingester


class TestRdfIngester:
    def _run_with_ttl(self, empty_graph, ttl: str) -> dict:  # type: ignore[no-untyped-def]
        ingester = _make_ingester(empty_graph)
        with tempfile.NamedTemporaryFile(
            suffix=".ttl", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write(ttl)
            ingester.local_path = Path(f.name)
        return ingester.ingest()

    def test_pollutant_concept_mapped(self, empty_graph) -> None:  # type: ignore[no-untyped-def]
        _, ttl = _build_external_graph()
        self._run_with_ttl(empty_graph, ttl)

        pollutant_class = URIRef(f"{WC}Pollutant")
        polluants = list(empty_graph.subjects(RDF.type, pollutant_class))
        assert len(polluants) >= 1

    def test_waterbody_concept_mapped(self, empty_graph) -> None:  # type: ignore[no-untyped-def]
        _, ttl = _build_external_graph()
        self._run_with_ttl(empty_graph, ttl)

        wb_class = URIRef(f"{WC}WaterBody")
        wbs = list(empty_graph.subjects(RDF.type, wb_class))
        assert len(wbs) >= 1

    def test_same_as_links_created(self, empty_graph) -> None:  # type: ignore[no-untyped-def]
        _, ttl = _build_external_graph()
        counts = self._run_with_ttl(empty_graph, ttl)
        assert counts["same_as_links"] >= 2

    def test_labels_copied(self, empty_graph) -> None:  # type: ignore[no-untyped-def]
        _, ttl = _build_external_graph()
        self._run_with_ttl(empty_graph, ttl)
        from rdflib.namespace import RDFS
        labels = list(empty_graph.objects(predicate=RDFS.label))
        assert any("arsenic" in str(lb).lower() for lb in labels)

    def test_local_iri_derivation(self, empty_graph) -> None:  # type: ignore[no-untyped-def]
        ingester = _make_ingester(empty_graph)
        ext = URIRef(f"{EXT}pollutant_001")
        local = ingester._local_iri_for(ext)
        assert str(local) == f"{WCD}concept/pollutant_001"
