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


def load_graph(path: Path, fmt: str | None = None, cfg: NamespacesConfig | None = None) -> Graph:
    """Load an existing serialised graph from disk. Format is auto-detected from extension."""
    _EXT_FMT = {".nt": "nt", ".owl": "xml", ".xml": "xml", ".ttl": "turtle", ".n3": "n3"}
    resolved_fmt = fmt or _EXT_FMT.get(Path(path).suffix.lower(), "xml")
    g = build_graph(cfg) if cfg is not None else Graph()
    g.parse(str(path), format=resolved_fmt)
    return g


def save_graph(g: Graph, path: Path, fmt: str = "xml") -> None:
    """Serialise graph to disk, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    g.serialize(destination=str(path), format=fmt)


def save_graph_oxigraph(nt_path: Path, store_path: Path) -> None:
    """Bulk-load an NT file into a persistent Oxigraph store directory."""
    import shutil
    import pyoxigraph as ox  # type: ignore[import]
    if store_path.exists():
        shutil.rmtree(store_path)
    store_path.mkdir(parents=True)
    ox_store = ox.Store(path=str(store_path))
    with open(nt_path, "rb") as fh:
        ox_store.bulk_load(fh, "application/n-triples")


def load_graph_oxigraph(store_path: Path) -> "OxigraphAdapter":  # type: ignore[return]
    """Open an existing Oxigraph store in read-only mode. Near-instant — no NT parsing needed."""
    import pyoxigraph as ox  # type: ignore[import]
    from water_ontology.oxigraph_adapter import OxigraphAdapter
    return OxigraphAdapter(ox.Store.read_only(str(store_path)))


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
