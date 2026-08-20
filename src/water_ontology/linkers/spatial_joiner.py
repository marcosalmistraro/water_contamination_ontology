"""Spatial joiner: link E-PRTR facilities and monitoring stations to river basin districts.

Loads polygon geometry from the EU RBD GeoJSON file (WISE_SoE), then:
  1. For each IndustrialFacility with lat/lon: adds wc:locatedInCatchment.
  2. For each MonitoringStation with lat/lon: adds wc:drainsToCatchment on its
     proxy WaterBody — bridging the Waterbase WaterBody island to the GeoJSON
     Catchment island so cross-domain queries work.

Requires shapely (>=2.0).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from rdflib import Graph, Namespace, URIRef

logger = logging.getLogger(__name__)

WC = Namespace("https://w3id.org/water-contamination/")
WCD = Namespace("https://w3id.org/water-contamination/data/")
GEO = Namespace("http://www.w3.org/2003/01/geo/wgs84_pos#")
GEO_SPARQL = Namespace("http://www.opengis.net/ont/geosparql#")


def _safe(fragment: str) -> str:
    return str(fragment).replace(" ", "_").replace("/", "-").replace(":", "_")


def _feature_id(props: dict[str, Any]) -> str:
    return str(
        props.get("thematicIdIdentifier")
        or props.get("rbdCode")
        or props.get("inspireIdLocalId")
        or props.get("waterBodyCode")
        or props.get("OBJECTID")
        or ""
    ).strip()


def _load_rbd_info(rbd_geojson: Path) -> list[tuple]:
    """Load RBD polygon features from GeoJSON.

    Returns a list of (shapely_geom, catchment_iri, waterbody_iri).
    Caller must ensure shapely is available.
    """
    from shapely.geometry import shape as shapely_shape

    with rbd_geojson.open(encoding="utf-8") as fh:
        collection = json.load(fh)

    rbd_info: list[tuple] = []
    for feat in collection.get("features", []):
        geom_raw = feat.get("geometry")
        if not geom_raw:
            continue
        props = feat.get("properties") or {}
        fid = _feature_id(props)
        if not fid:
            continue
        try:
            geom = shapely_shape(geom_raw)
        except Exception:
            continue
        rbd_info.append((geom, WCD[f"catchment/{_safe(fid)}"], WCD[f"waterbody/{_safe(fid)}"]))

    logger.info("[SpatialJoin] Loaded %d RBD polygons from %s", len(rbd_info), rbd_geojson.name)
    return rbd_info


def link_facilities_to_rbds(
    graph: Graph,
    rbd_geojson: Path,
) -> dict[str, int]:
    """Point-in-polygon join: add wc:locatedInCatchment for each matched facility.

    Returns counts: {'facilities_checked', 'facilities_linked', 'rbds_loaded'}.
    """
    try:
        from shapely.geometry import Point
        from shapely.strtree import STRtree
    except ImportError:
        logger.error("[SpatialJoin] shapely not installed — skipping")
        return {"facilities_checked": 0, "facilities_linked": 0, "rbds_loaded": 0}

    if not rbd_geojson.exists():
        logger.warning("[SpatialJoin] RBD GeoJSON not found: %s — skipping", rbd_geojson)
        return {"facilities_checked": 0, "facilities_linked": 0, "rbds_loaded": 0}

    rbd_info = _load_rbd_info(rbd_geojson)
    if not rbd_info:
        logger.warning("[SpatialJoin] No RBD geometries loaded from %s", rbd_geojson.name)
        return {"facilities_checked": 0, "facilities_linked": 0, "rbds_loaded": 0}

    tree = STRtree([info[0] for info in rbd_info])

    q = """
        PREFIX wc: <https://w3id.org/water-contamination/>
        PREFIX geo: <http://www.w3.org/2003/01/geo/wgs84_pos#>
        SELECT ?fac ?lat ?lon WHERE {
            ?fac a wc:IndustrialFacility ;
                 geo:lat ?lat ;
                 geo:long ?lon .
        }
    """
    facility_rows = list(graph.query(q))
    logger.info("[SpatialJoin] Checking %d facilities against %d RBDs", len(facility_rows), len(rbd_info))

    linked = 0
    for row in facility_rows:
        fac_iri: URIRef = row[0]  # type: ignore[assignment]
        point = Point(float(row[2]), float(row[1]))  # (lon, lat)
        for idx in tree.query(point, predicate="within"):
            graph.add((fac_iri, WC.locatedInCatchment, rbd_info[idx][1]))
            linked += 1
            break

    logger.info("[SpatialJoin] Linked %d / %d facilities to RBDs", linked, len(facility_rows))
    return {
        "facilities_checked": len(facility_rows),
        "facilities_linked": linked,
        "rbds_loaded": len(rbd_info),
    }


def link_stations_to_rbds(
    graph: Graph,
    rbd_geojson: Path,
) -> dict[str, int]:
    """Point-in-polygon join: add wc:drainsToCatchment on each station's WaterBody.

    Bridges the Waterbase WaterBody island (proxy IRIs based on site IDs) to the
    GeoJSON Catchment island so queries like "observations near RBD X" work.

    Returns counts: {'stations_checked', 'stations_linked', 'rbds_loaded'}.
    """
    try:
        from shapely.geometry import Point
        from shapely.strtree import STRtree
    except ImportError:
        logger.error("[SpatialJoin] shapely not installed — skipping")
        return {"stations_checked": 0, "stations_linked": 0, "rbds_loaded": 0}

    if not rbd_geojson.exists():
        logger.warning("[SpatialJoin] RBD GeoJSON not found: %s — skipping", rbd_geojson)
        return {"stations_checked": 0, "stations_linked": 0, "rbds_loaded": 0}

    rbd_info = _load_rbd_info(rbd_geojson)
    if not rbd_info:
        return {"stations_checked": 0, "stations_linked": 0, "rbds_loaded": 0}

    tree = STRtree([info[0] for info in rbd_info])

    q = """
        PREFIX wc: <https://w3id.org/water-contamination/>
        PREFIX geo: <http://www.w3.org/2003/01/geo/wgs84_pos#>
        SELECT ?station ?wb ?lat ?lon WHERE {
            ?station a wc:MonitoringStation ;
                     wc:monitors ?wb ;
                     geo:lat ?lat ;
                     geo:long ?lon .
        }
    """
    station_rows = list(graph.query(q))
    logger.info("[SpatialJoin] Checking %d stations against %d RBDs", len(station_rows), len(rbd_info))

    linked = 0
    for row in station_rows:
        wb_iri: URIRef = row[1]  # type: ignore[assignment]
        point = Point(float(row[3]), float(row[2]))  # (lon, lat)
        for idx in tree.query(point, predicate="within"):
            graph.add((wb_iri, WC.drainsToCatchment, rbd_info[idx][1]))
            linked += 1
            break

    logger.info("[SpatialJoin] Linked %d / %d station water bodies to RBDs", linked, len(station_rows))
    return {
        "stations_checked": len(station_rows),
        "stations_linked": linked,
        "rbds_loaded": len(rbd_info),
    }
