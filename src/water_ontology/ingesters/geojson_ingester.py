"""EEA/OSM GeoJSON ingester: river basin districts → WaterBody + Catchment triples."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from rdflib import Graph, Literal, Namespace, RDF, XSD

from water_ontology.config import SourceConfig
from water_ontology.ingesters.base import BaseIngester

logger = logging.getLogger(__name__)

WC = Namespace("https://w3id.org/water-contamination/")
WCD = Namespace("https://w3id.org/water-contamination/data/")
GEO_SPARQL = Namespace("http://www.opengis.net/ont/geosparql#")


def _safe(fragment: str) -> str:
    return str(fragment).replace(" ", "_").replace("/", "-").replace(":", "_")


class GeoJsonIngester(BaseIngester):
    """Ingest GeoJSON water body / catchment features into the knowledge graph."""

    source_name = "EEA-GeoJSON"

    # Feature-property → ontology class mapping.
    # The GeoJSON schema varies by EEA dataset; defaults target River Basin Districts.
    _WATERBODY_PROPS: dict[str, str] = {
        "rbdCode": "rbdCode",
        "rbdName": "waterBodyName",
        "countryCode": "countryCode",
        "areaKm2": "areaKm2",
    }
    _CATCHMENT_PROPS: dict[str, str] = {
        "rbdCode": "rbdCode",
        "rbdName": "catchmentName",
        "countryCode": "countryCode",
    }

    def __init__(
        self,
        graph: Graph,
        cfg: SourceConfig,
        raw_dir: Path = Path("data/raw"),
        mode: str = "waterbody",  # "waterbody" | "catchment" | "both"
    ) -> None:
        super().__init__(graph, raw_dir)
        self.cfg = cfg
        self.local_path = Path(cfg.local_file) if cfg.local_file else raw_dir / "features.geojson"
        self.mode = mode

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def download(self) -> None:
        self._download_file(self.cfg.url, self.local_path)

    # ------------------------------------------------------------------
    # Ingest
    # ------------------------------------------------------------------

    def ingest(self) -> dict[str, int]:
        logger.info("[GeoJSON] Parsing %s", self.local_path.name)
        with self.local_path.open(encoding="utf-8") as fh:
            collection: dict[str, Any] = json.load(fh)

        features: list[dict[str, Any]] = collection.get("features", [])
        counts: dict[str, int] = {"water_bodies": 0, "catchments": 0}

        for feat in features:
            props: dict[str, Any] = feat.get("properties") or {}
            geom: dict[str, Any] | None = feat.get("geometry")

            feature_id = str(
                props.get("rbdCode")
                or props.get("waterBodyCode")
                or props.get("id")
                or props.get("FID")
                or ""
            ).strip()

            if not feature_id:
                continue

            if self.mode in ("waterbody", "both"):
                self._add_water_body(feature_id, props, geom)
                counts["water_bodies"] += 1

            if self.mode in ("catchment", "both"):
                self._add_catchment(feature_id, props, geom)
                counts["catchments"] += 1

        logger.info("[GeoJSON] %s", counts)
        return counts

    # ------------------------------------------------------------------
    # Private triple builders
    # ------------------------------------------------------------------

    def _add_water_body(
        self,
        feature_id: str,
        props: dict[str, Any],
        geom: dict[str, Any] | None,
    ) -> None:
        iri = WCD[f"waterbody/{_safe(feature_id)}"]
        g = self.graph
        g.add((iri, RDF.type, WC.WaterBody))
        g.add((iri, WC.waterBodyId, Literal(feature_id, datatype=XSD.string)))

        name = str(props.get("rbdName") or props.get("waterBodyName") or "").strip()
        if name:
            g.add((iri, WC.waterBodyName, Literal(name, datatype=XSD.string)))

        cc = str(props.get("countryCode") or "").strip()
        if cc:
            g.add((iri, WC.countryCode, Literal(cc, datatype=XSD.string)))

        rbd = str(props.get("rbdCode") or "").strip()
        if rbd:
            g.add((iri, WC.rbdCode, Literal(rbd, datatype=XSD.string)))

        if geom:
            wkt = _geom_to_wkt(geom)
            if wkt:
                g.add((iri, GEO_SPARQL.hasGeometry, Literal(wkt, datatype=GEO_SPARQL.wktLiteral)))

    def _add_catchment(
        self,
        feature_id: str,
        props: dict[str, Any],
        geom: dict[str, Any] | None,
    ) -> None:
        iri = WCD[f"catchment/{_safe(feature_id)}"]
        g = self.graph
        g.add((iri, RDF.type, WC.Catchment))
        g.add((iri, WC.catchmentId, Literal(feature_id, datatype=XSD.string)))

        name = str(props.get("rbdName") or props.get("catchmentName") or "").strip()
        if name:
            g.add((iri, WC.catchmentName, Literal(name, datatype=XSD.string)))

        cc = str(props.get("countryCode") or "").strip()
        if cc:
            g.add((iri, WC.countryCode, Literal(cc, datatype=XSD.string)))

        if geom:
            wkt = _geom_to_wkt(geom)
            if wkt:
                g.add((iri, GEO_SPARQL.hasGeometry, Literal(wkt, datatype=GEO_SPARQL.wktLiteral)))

        # Link the matching WaterBody to this Catchment
        wb_iri = WCD[f"waterbody/{_safe(feature_id)}"]
        g.add((wb_iri, WC.drainsToCatchment, iri))


# ---------------------------------------------------------------------------
# GeoJSON → WKT helpers (minimal, no shapely dependency)
# ---------------------------------------------------------------------------

def _geom_to_wkt(geom: dict[str, Any]) -> str:
    """Convert a simple GeoJSON geometry dict to a WKT string (best-effort)."""
    gtype = geom.get("type", "")
    coords = geom.get("coordinates")
    if not coords:
        return ""
    try:
        if gtype == "Point":
            return f"POINT ({coords[0]} {coords[1]})"
        if gtype == "MultiPolygon":
            rings = " , ".join(
                f"(({_ring(r[0])}))" for r in coords if r
            )
            return f"MULTIPOLYGON ({rings})"
        if gtype == "Polygon":
            return f"POLYGON (({_ring(coords[0])}))"
        if gtype == "MultiPoint":
            pts = " , ".join(f"({c[0]} {c[1]})" for c in coords)
            return f"MULTIPOINT ({pts})"
    except (IndexError, TypeError):
        pass
    return ""


def _ring(points: list[list[float]]) -> str:
    return ", ".join(f"{p[0]} {p[1]}" for p in points)
