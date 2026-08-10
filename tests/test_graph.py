"""Tests for graph initialisation and serialisation."""

from __future__ import annotations

from pathlib import Path

import pytest
from rdflib import OWL, RDF, URIRef

from water_ontology.graph import build_graph, save_graph, load_graph

WC = "https://w3id.org/water-contamination/"


def test_build_graph_declares_core_classes(empty_graph):  # type: ignore[no-untyped-def]
    for cls in ["IndustrialFacility", "EmissionEvent", "WaterBody", "Pollutant"]:
        iri = URIRef(f"{WC}{cls}")
        assert (iri, RDF.type, OWL.Class) in empty_graph


def test_save_and_load_roundtrip(empty_graph) -> None:
    import tempfile, os
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "test.owl"
        save_graph(empty_graph, out)
        assert out.exists()
        loaded = load_graph(out)
        assert len(loaded) == len(empty_graph)
