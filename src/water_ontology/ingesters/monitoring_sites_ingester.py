"""Monitoring sites ingester: patch lat/lon onto Waterbase stations from EEA ArcGIS.

Two-pass strategy:
  Pass 1 — EIONET service (WISE5 eionetMonitoringSiteCode scheme)
  Pass 2 — WFD2022 service (WISE6 euMonitoringSiteCode scheme, batch IN-query)

The Waterbase DisaggregatedData uses both schemes. Pass 1 covers ~487 stations,
Pass 2 covers the remaining ~1681 stations that use WISE6 identifiers.
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

_WFD_URL = (
    "https://water.discomap.eea.europa.eu"
    "/arcgis/rest/services/WISE_WFD/WFD2022_MonitoringSite_WM/MapServer/0/query"
)
_WFD_BATCH = 100   # IDs per IN-clause request
_WFD_FIELDS = "thematicIdIdentifier,lat,lon"


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
        self.wfd_cache = self.local_path.parent / "wfd_crosswalk.json"
        self.page_size = cfg.page_size or 1000
        self.base_url = cfg.url

    # ------------------------------------------------------------------
    # Download — Pass 1: EIONET monitoring sites (paginated)
    # ------------------------------------------------------------------

    def download(self) -> None:
        if self.local_path.exists():
            logger.info("[%s] Already downloaded: %s", self.source_name, self.local_path.name)
            return

        logger.info("[%s] Downloading EIONET monitoring sites (paginated, page=%d)", self.source_name, self.page_size)
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
            logger.info("[%s] Fetched %d EIONET sites (offset=%d)", self.source_name, len(all_features), offset)
            if len(features) < self.page_size:
                break
            offset += self.page_size

        collection = {"type": "FeatureCollection", "features": all_features}
        self.local_path.parent.mkdir(parents=True, exist_ok=True)
        self.local_path.write_text(json.dumps(collection), encoding="utf-8")
        logger.info("[%s] Saved %d EIONET sites → %s", self.source_name, len(all_features), self.local_path)

    # ------------------------------------------------------------------
    # Ingest
    # ------------------------------------------------------------------

    def ingest(self) -> dict[str, int]:
        # --- Pass 1: EIONET sites (eionetMonitoringSiteCode) ---
        with self.local_path.open(encoding="utf-8") as fh:
            collection = json.load(fh)
        eionet_sites = _build_lookup(collection.get("features", []))
        logger.info("[%s] EIONET lookup: %d sites with coordinates", self.source_name, len(eionet_sites))

        # Get all station IRIs + IDs from graph
        station_map: dict[str, URIRef] = {}  # sid → iri
        q = """
            PREFIX wc: <https://w3id.org/water-contamination/>
            SELECT ?iri ?sid WHERE {
                ?iri a wc:MonitoringStation ;
                     wc:stationId ?sid .
            }
        """
        for row in self.graph.query(q):
            station_map[str(row[1])] = row[0]  # type: ignore[assignment]

        if not station_map:
            logger.warning(
                "[%s] No MonitoringStation individuals found in graph — "
                "run the waterbase ingester first, then re-run this ingester to patch coordinates.",
                self.source_name,
            )
            return {"stations_patched": 0, "eionet_patched": 0, "wfd_patched": 0}

        # Patch pass 1
        p1 = _patch_stations(self.graph, station_map, eionet_sites)
        logger.info("[%s] Pass 1 (EIONET): patched %d stations", self.source_name, p1)

        # --- Pass 2: WFD2022 batch lookup for remaining unmatched stations ---
        unmatched = _find_unmatched(self.graph, station_map)
        logger.info("[%s] Unmatched after pass 1: %d stations", self.source_name, len(unmatched))

        wfd_sites = self._fetch_wfd_sites(list(unmatched))
        p2 = _patch_stations(self.graph, station_map, wfd_sites)
        logger.info("[%s] Pass 2 (WFD2022): patched %d stations", self.source_name, p2)

        total = p1 + p2
        logger.info(
            "[%s] Total stations in graph: %d | total patched: %d",
            self.source_name, len(station_map), total,
        )
        return {"stations_patched": total, "eionet_patched": p1, "wfd_patched": p2}

    # ------------------------------------------------------------------
    # Pass 2: WFD2022 batch IN-query
    # ------------------------------------------------------------------

    def _fetch_wfd_sites(self, station_ids: list[str]) -> dict[str, dict]:
        """Batch-query WFD2022 for specific station IDs; cache results to disk."""
        if not station_ids:
            return {}

        if self.wfd_cache.exists():
            logger.info("[%s] Loading WFD crosswalk from cache: %s", self.source_name, self.wfd_cache.name)
            with self.wfd_cache.open(encoding="utf-8") as fh:
                return json.load(fh)

        logger.info("[%s] Querying WFD2022 for %d station IDs (batch=%d)", self.source_name, len(station_ids), _WFD_BATCH)
        all_sites: dict[str, dict] = {}

        for i in range(0, len(station_ids), _WFD_BATCH):
            batch = station_ids[i : i + _WFD_BATCH]
            id_list = ", ".join(f"'{sid}'" for sid in batch)
            where_clause = f"thematicIdIdentifier IN ({id_list})"
            params = {
                "where": where_clause,
                "outFields": _WFD_FIELDS,
                "returnGeometry": "false",
                "f": "geojson",
            }
            try:
                resp = requests.post(_WFD_URL, data=params, timeout=30)
                resp.raise_for_status()
                features = resp.json().get("features", [])
                batch_sites = _build_lookup(features)
                all_sites.update(batch_sites)
            except Exception as exc:
                logger.warning("[%s] WFD batch %d failed: %s", self.source_name, i // _WFD_BATCH, exc)

            if (i // _WFD_BATCH + 1) % 5 == 0:
                logger.info("[%s] WFD progress: %d/%d batches, %d matched", self.source_name, i // _WFD_BATCH + 1, (len(station_ids) + _WFD_BATCH - 1) // _WFD_BATCH, len(all_sites))

        self.wfd_cache.write_text(json.dumps(all_sites), encoding="utf-8")
        logger.info("[%s] WFD crosswalk: %d matches → %s", self.source_name, len(all_sites), self.wfd_cache.name)
        return all_sites


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_lookup(features: list[dict]) -> dict[str, dict]:
    """Build {thematicIdIdentifier → {lat, lon}} from a GeoJSON feature list."""
    out: dict[str, dict] = {}
    for feat in features:
        pp = feat.get("properties") or {}
        sid = str(pp.get("thematicIdIdentifier") or "").strip()
        lat = pp.get("lat")
        lon = pp.get("lon")
        if sid and lat is not None and lon is not None:
            try:
                out[sid] = {"lat": float(lat), "lon": float(lon)}
            except (TypeError, ValueError) as exc:
                logger.warning("[MonitoringSites] Bad coordinates for site %r: %s", sid, exc)
    return out


def _patch_stations(graph: Graph, station_map: dict[str, URIRef], sites: dict[str, dict]) -> int:
    """Add geo:lat/geo:long to stations in station_map that appear in sites. Returns count patched."""
    patched = 0
    for sid, iri in station_map.items():
        site = sites.get(sid)
        if not site:
            continue
        if (iri, GEO.lat, None) in graph:
            continue  # already has coordinates
        graph.add((iri, GEO.lat, Literal(site["lat"], datatype=XSD.decimal)))
        graph.add((iri, GEO.long, Literal(site["lon"], datatype=XSD.decimal)))
        patched += 1
    return patched


def _find_unmatched(graph: Graph, station_map: dict[str, URIRef]) -> set[str]:
    """Return station IDs that have no geo:lat triple yet."""
    return {sid for sid, iri in station_map.items() if (iri, GEO.lat, None) not in graph}
