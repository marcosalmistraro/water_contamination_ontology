"""Shared pytest fixtures."""

from __future__ import annotations

import pytest
from rdflib import Graph

from water_ontology.config import NamespacesConfig
from water_ontology.graph import build_graph


@pytest.fixture()
def empty_graph() -> Graph:
    cfg = NamespacesConfig(
        base_iri="https://w3id.org/water-contamination/",
        namespaces={
            "wc": "https://w3id.org/water-contamination/",
            "wcd": "https://w3id.org/water-contamination/data/",
        },
        ontology_file="data/ontology/water_contamination.owl",
        shacl_file="data/ontology/shacl_shapes.ttl",
    )
    return build_graph(cfg)
