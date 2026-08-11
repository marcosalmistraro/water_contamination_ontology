"""Monitoring sites ingester: patch lat/lon onto Waterbase stations from EEA ArcGIS.

The Waterbase DisaggregatedData CSV has no coordinates.  The EEA WISE monitoring
sites ArcGIS layer has lat/lon and water body links keyed by the same
thematicIdIdentifier used as monitoringSiteIdentifier in the CSV.  This ingester
downloads all monitoring sites (paginated), then patches geo:lat / geo:long onto
any station IRI already in the graph whose stationId matches.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from urllib.parse import urlencode

import requests
from rdflib import Graph, Literal, Namespace, RDF, XSD, URIRef

from water_ontology.config import SourceConfig
from water_ontology.ingesters.base import BaseIngester

logger = logging.getLogger(__name__)

WC = Namespace("https://w3id.org/water-contamination/")
WCD = Namespace("https://w3id.org/water-contamination/data/")
GEO = Namespace("http://www.w3.org/2003/01/geo/wgs84_pos#")


def _safe(fragment: str) -> str:
    return str(fragment).replace(" ", "_").replace("/", "-").replace(":", "_")


class MonitoringSitesIngester(BaseIngester):
    """Patch EEA monitoring site coordinates onto existing station nodes."""

    source_name = "WISE-MonitoringSites"

    def __init__(
        self,
        graph: Graph,
        cfg: SourceConfig,
        raw_dir: Path = Path("data/raw"),
    ) -> None:
        super().__init__(graph, raw_dir)
        self.cfg = cfg
        self.local_path = Path(cfg.local_file) if cfg.local_file else raw_dir / "monitoring_sites.geojson"
        self.page_size = cfg.page_size or 1000
        self.base_url = cfg.url

    # ------------------------------------------------------------------
    # Download (paginated ArcGIS query)
    # ------------------------------------------------------------------

    def download(self) -> None:
        if self.local_path.exists():
            logger.info("[%s] Already downloaded: %s", self.source_name, self.local_path.name)
            return

        logger.info("[%s] Downloading monitoring sites (paginated, page=%d)", self.source_name, self.page_size)
        all_features: list[dict] = []
        offset = 0

        while True:
            params = {
                "where": "1=1",
                "outFields": "thematicIdIdentifier,lat,lon,countryCode",
                "returnGeometry": "false",
                "resultOffset": str(offset),
                "resultRecordCount": str(self.page_size),
                "f": "geojson",
            }
            url = f"{self.base_url}?{urlencode(params)}"
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            features = data.get("features", [])
            if not features:
                break
            all_features.extend(features)
            logger.info("[%s] Fetched %d sites (offset=%d)", self.source_name, len(all_features), offset)
            if len(features) < self.page_size:
                break
            offset += self.page_size

        collection = {"type": "FeatureCollection", "features": all_features}
        self.local_path.parent.mkdir(parents=True, exist_ok=True)
        self.local_path.write_text(json.dumps(collection), encoding="utf-8")
        logger.info("[%s] Saved %d sites → %s", self.source_name, len(all_features), self.local_path)

    # ------------------------------------------------------------------
    # Ingest — patch lat/lon onto existing station IRIs
    # ------------------------------------------------------------------

    def ingest(self) -> dict[str, int]:
        with self.local_path.open(encoding="utf-8") as fh:
            collection = json.load(fh)
        features = collection.get("features", [])
        logger.info("[%s] Loaded %d monitoring sites", self.source_name, len(features))

        # Build lookup: stationId → {lat, lon} from downloaded features
        sites: dict[str, dict] = {}
        for feat in features:
            pp = feat.get("properties") or {}
            sid = str(pp.get("thematicIdIdentifier") or "").strip()
            lat = pp.get("lat")
            lon = pp.get("lon")
            if sid and lat is not None and lon is not None:
                try:
                    sites[sid] = {"lat": float(lat), "lon": float(lon)}
                except (TypeError, ValueError):
                    pass

        # Query existing station IRIs from the graph
        matched = patched = 0
        q = """
            PREFIX wc: <https://w3id.org/water-contamination/>
            SELECT ?iri ?sid WHERE {
                ?iri a wc:MonitoringStation ;
                     wc:stationId ?sid .
            }
        """
        for row in self.graph.query(q):
            iri: URIRef = row[0]  # type: ignore[assignment]
            sid = str(row[1])
            matched += 1
            site = sites.get(sid)
            if not site:
                continue
            g = self.graph
            g.add((iri, GEO.lat, Literal(site["lat"], datatype=XSD.decimal)))
            g.add((iri, GEO.long, Literal(site["lon"], datatype=XSD.decimal)))
            patched += 1

        logger.info(
            "[%s] Stations in graph: %d | lat/lon patched: %d | sites downloaded: %d",
            self.source_name, matched, patched, len(sites),
        )
        return {"stations_patched": patched, "sites_downloaded": len(sites)}
