"""GET /graph/stats and GET /health."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends
from rdflib import RDF, Graph

from water_ontology.api.deps import get_graph
from water_ontology.api.models import GraphStats, HealthResponse

logger = logging.getLogger(__name__)
router = APIRouter()

_CORE_CLASSES = [
    "IndustrialFacility",
    "EmissionEvent",
    "WaterBody",
    "MonitoringStation",
    "Pollutant",
    "ComplianceThreshold",
    "Catchment",
    "RegulationDocument",
]
_WC = "https://w3id.org/water-contamination/"


@router.get("/health", response_model=HealthResponse)
def health(graph: Graph = Depends(get_graph)) -> HealthResponse:
    """Liveness check — confirms the graph is loaded."""
    return HealthResponse(
        status="ok",
        graph_loaded=True,
        triple_count=len(graph),
    )


@router.get("/graph/stats", response_model=GraphStats)
def graph_stats(graph: Graph = Depends(get_graph)) -> GraphStats:
    """Return triple count and per-class individual counts."""
    from rdflib import URIRef

    class_counts: dict[str, int] = {}
    for cls_name in _CORE_CLASSES:
        cls_iri = URIRef(f"{_WC}{cls_name}")
        count = sum(1 for _ in graph.subjects(RDF.type, cls_iri))
        class_counts[cls_name] = count

    return GraphStats(
        total_triples=len(graph),
        class_counts=class_counts,
        ontology_file=os.getenv("ONTOLOGY_FILE", "data/ontology/water_contamination.nt"),
    )
