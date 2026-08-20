"""INSPIRE / EnvThes RDF/Turtle ingester: align external vocabulary to local ontology."""

from __future__ import annotations

import logging
from pathlib import Path

from rdflib import RDF, RDFS, SKOS, XSD, Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL

from water_ontology.config import SourceConfig
from water_ontology.ingesters.base import BaseIngester

logger = logging.getLogger(__name__)

WC = Namespace("https://w3id.org/water-contamination/")
WCD = Namespace("https://w3id.org/water-contamination/data/")
SKOS_NS = Namespace("http://www.w3.org/2004/02/skos/core#")

# EnvThes concept IRIs we care about — used to scope which concepts are imported.
# These are the top-level terms whose narrower concepts we pull into our graph.
_CONCEPTS_OF_INTEREST = frozenset(
    [
        "http://vocabs.lter-europe.net/EnvThes/10471",   # water quality
        "http://vocabs.lter-europe.net/EnvThes/10486",   # pollutant
        "http://vocabs.lter-europe.net/EnvThes/10488",   # heavy metals
        "http://vocabs.lter-europe.net/EnvThes/10030",   # industrial pollution
        "http://vocabs.lter-europe.net/EnvThes/10047",   # water pollution
    ]
)


class RdfIngester(BaseIngester):
    """
    Parse an external RDF/Turtle vocabulary (EnvThes / INSPIRE) and:

    1. Import relevant SKOS concepts as Pollutant or WaterBody individuals.
    2. Assert owl:sameAs links between local IRIs and external concept IRIs.
    3. Bring in skos:prefLabel / skos:definition as rdfs:label / rdfs:comment.
    """

    source_name = "EnvThes-RDF"

    def __init__(
        self,
        graph: Graph,
        cfg: SourceConfig,
        raw_dir: Path = Path("data/raw"),
        fmt: str = "turtle",
    ) -> None:
        super().__init__(graph, raw_dir)
        self.cfg = cfg
        self.local_path = Path(cfg.local_file) if cfg.local_file else raw_dir / "envthes.ttl"
        self.fmt = fmt

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def download(self) -> None:
        self._download_file(self.cfg.url, self.local_path)

    # ------------------------------------------------------------------
    # Ingest
    # ------------------------------------------------------------------

    def ingest(self) -> dict[str, int]:
        logger.info("[RDF] Parsing %s (%s)", self.local_path.name, self.fmt)
        external = Graph()
        external.parse(str(self.local_path), format=self.fmt)
        logger.info("[RDF] External graph: %d triples", len(external))

        counts: dict[str, int] = {"concepts_imported": 0, "same_as_links": 0}

        in_scope = self._collect_in_scope_concepts(external)
        logger.info("[RDF] In-scope concepts: %d", len(in_scope))

        for concept_iri in in_scope:
            mapped = self._classify_concept(concept_iri, external)
            if mapped:
                counts["concepts_imported"] += 1

            # owl:sameAs between local IRI and external concept
            local_iri = self._local_iri_for(concept_iri)
            self.graph.add((local_iri, OWL.sameAs, concept_iri))
            counts["same_as_links"] += 1

            # Copy labels and definitions
            self._copy_labels(concept_iri, local_iri, external)

        logger.info("[RDF] %s", counts)
        return counts

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _collect_in_scope_concepts(self, ext: Graph) -> set[URIRef]:
        """Return all SKOS concepts that are narrower-or-equal to our topic IRIs."""
        in_scope: set[URIRef] = set()

        # Seed with known top-level concepts
        for seed in _CONCEPTS_OF_INTEREST:
            seed_ref = URIRef(seed)
            if (seed_ref, RDF.type, SKOS.Concept) in ext:
                in_scope.add(seed_ref)

        # BFS over skos:narrower and skos:narrowerTransitive
        queue = list(in_scope)
        while queue:
            concept = queue.pop()
            for narrower in ext.objects(concept, SKOS.narrower):
                if isinstance(narrower, URIRef) and narrower not in in_scope:
                    in_scope.add(narrower)
                    queue.append(narrower)

        # Fallback: if nothing matched the seeds, import all Concepts
        if not in_scope:
            logger.warning("[RDF] No seed concepts found; importing all skos:Concept instances")
            in_scope = {
                s for s in ext.subjects(RDF.type, SKOS.Concept) if isinstance(s, URIRef)
            }

        return in_scope

    def _classify_concept(self, concept_iri: URIRef, ext: Graph) -> bool:
        """Map an external concept to a local ontology class and add it."""
        label = self._pref_label(concept_iri, ext).lower()
        local_iri = self._local_iri_for(concept_iri)

        if any(kw in label for kw in ("pollutant", "contaminant", "metal", "chemical")):
            self.graph.add((local_iri, RDF.type, WC.Pollutant))
            self.graph.add((local_iri, WC.pollutantName, Literal(label, datatype=XSD.string)))
            self.graph.add((local_iri, WC.medium, Literal("water", datatype=XSD.string)))
            return True

        if any(kw in label for kw in ("water body", "river", "lake", "estuary", "coastal")):
            self.graph.add((local_iri, RDF.type, WC.WaterBody))
            self.graph.add((local_iri, WC.waterBodyName, Literal(label, datatype=XSD.string)))
            return True

        return False

    def _copy_labels(
        self, ext_iri: URIRef, local_iri: URIRef, ext: Graph
    ) -> None:
        for obj in ext.objects(ext_iri, SKOS.prefLabel):
            self.graph.add((local_iri, RDFS.label, obj))
        for obj in ext.objects(ext_iri, SKOS.definition):
            self.graph.add((local_iri, RDFS.comment, obj))
        for obj in ext.objects(ext_iri, SKOS.altLabel):
            self.graph.add((local_iri, SKOS_NS.altLabel, obj))

    def _local_iri_for(self, ext_iri: URIRef) -> URIRef:
        """Derive a local WCD IRI from an external concept IRI fragment."""
        fragment = str(ext_iri).rstrip("/").rsplit("/", 1)[-1]
        return WCD[f"concept/{fragment}"]

    def _pref_label(self, iri: URIRef, ext: Graph) -> str:
        for obj in ext.objects(iri, SKOS.prefLabel):
            lang = getattr(obj, "language", None)
            if lang in ("en", None):
                return str(obj)
        # Fall back to any label
        for obj in ext.objects(iri, SKOS.prefLabel):
            return str(obj)
        return str(iri).rsplit("/", 1)[-1]
