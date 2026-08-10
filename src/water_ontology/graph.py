"""rdflib graph initialisation and shared namespace management."""

from __future__ import annotations

from pathlib import Path

from rdflib import Graph, Literal, Namespace, RDF, RDFS, OWL, XSD
from rdflib.namespace import NamespaceManager

from water_ontology.config import NamespacesConfig, load_ontology_config

# Canonical ontology namespaces ------------------------------------------------
WC = Namespace("https://w3id.org/water-contamination/")
WCD = Namespace("https://w3id.org/water-contamination/data/")


def build_graph(cfg: NamespacesConfig | None = None) -> Graph:
    """Create and return a fresh rdflib ConjunctiveGraph bound to all namespaces."""
    if cfg is None:
        cfg = load_ontology_config()

    g = Graph()
    for prefix, iri in cfg.namespaces.items():
        g.bind(prefix, Namespace(iri))

    _declare_ontology_classes(g)
    return g


def load_graph(path: Path, fmt: str = "xml", cfg: NamespacesConfig | None = None) -> Graph:
    """Load an existing serialised graph from disk."""
    g = build_graph(cfg) if cfg is not None else Graph()
    g.parse(str(path), format=fmt)
    return g


def save_graph(g: Graph, path: Path, fmt: str = "xml") -> None:
    """Serialise graph to disk, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    g.serialize(destination=str(path), format=fmt)


def _declare_ontology_classes(g: Graph) -> None:
    """Assert OWL class declarations for the eight core ontology classes."""
    classes = [
        "IndustrialFacility",
        "EmissionEvent",
        "WaterBody",
        "MonitoringStation",
        "Pollutant",
        "ComplianceThreshold",
        "Catchment",
        "RegulationDocument",
    ]
    for cls in classes:
        iri = WC[cls]
        g.add((iri, RDF.type, OWL.Class))
        g.add((iri, RDFS.label, Literal(cls)))

    # Object properties
    _add_object_property(g, "hasEmissionEvent", WC.IndustrialFacility, WC.EmissionEvent)
    _add_object_property(g, "involvesPollutant", WC.EmissionEvent, WC.Pollutant)
    _add_object_property(g, "locatedInCatchment", WC.IndustrialFacility, WC.Catchment)
    _add_object_property(g, "monitors", WC.MonitoringStation, WC.WaterBody)
    _add_object_property(g, "drainsToCatchment", WC.WaterBody, WC.Catchment)
    _add_object_property(g, "hasThreshold", WC.Pollutant, WC.ComplianceThreshold)
    _add_object_property(g, "regulatedBy", WC.ComplianceThreshold, WC.RegulationDocument)

    # Datatype properties (key ones only; full schema in shacl_shapes.ttl)
    for prop, domain, range_ in [
        ("facilityId", WC.IndustrialFacility, XSD.string),
        ("facilityName", WC.IndustrialFacility, XSD.string),
        ("latitude", WC.IndustrialFacility, XSD.decimal),
        ("longitude", WC.IndustrialFacility, XSD.decimal),
        ("reportingYear", WC.EmissionEvent, XSD.integer),
        ("quantityKg", WC.EmissionEvent, XSD.decimal),
        ("medium", WC.EmissionEvent, XSD.string),
        ("pollutantName", WC.Pollutant, XSD.string),
        ("casNumber", WC.Pollutant, XSD.string),
    ]:
        g.add((WC[prop], RDF.type, OWL.DatatypeProperty))
        g.add((WC[prop], RDFS.domain, domain))
        g.add((WC[prop], RDFS.range, range_))


def _add_object_property(
    g: Graph, name: str, domain: Namespace, range_: Namespace
) -> None:
    g.add((WC[name], RDF.type, OWL.ObjectProperty))
    g.add((WC[name], RDFS.domain, domain))
    g.add((WC[name], RDFS.range, range_))
