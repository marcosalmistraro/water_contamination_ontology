"""Spatial joiner: link E-PRTR facilities to river basin districts.

Loads polygon geometry from the EU RBD GeoJSON file (WISE_SoE), then for each
IndustrialFacility with lat/lon in the graph checks which RBD polygon contains
the point and adds a wc:locatedInCatchment triple.

Requires shapely (>=2.0).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from rdflib import Graph, Literal, Namespace, RDF, XSD, URIRef

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


def link_facilities_to_rbds(
    graph: Graph,
    rbd_geojson: Path,
) -> dict[str, int]:
    """Point-in-polygon join: add wc:locatedInCatchment for each matched facility.

    Returns counts: {'facilities_checked', 'facilities_linked', 'rbds_loaded'}.
    """
    try:
        from shapely.geometry import Point, shape as shapely_shape
        from shapely.strtree import STRtree
    except ImportError:
        logger.error("[SpatialJoin] shapely not installed — skipping")
        return {"facilities_checked": 0, "facilities_linked": 0, "rbds_loaded": 0}

    if not rbd_geojson.exists():
        logger.warning("[SpatialJoin] RBD GeoJSON not found: %s — skipping", rbd_geojson)
        return {"facilities_checked": 0, "facilities_linked": 0, "rbds_loaded": 0}

    # 1. Load RBD polygons from GeoJSON
    with rbd_geojson.open(encoding="utf-8") as fh:
        collection = json.load(fh)

    rbd_info: list[tuple[Any, URIRef, URIRef]] = []  # (geom, catchment_iri, waterbody_iri)
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
        catchment_iri = WCD[f"catchment/{_safe(fid)}"]
        waterbody_iri = WCD[f"waterbody/{_safe(fid)}"]
        rbd_info.append((geom, catchment_iri, waterbody_iri))

    if not rbd_info:
        logger.warning("[SpatialJoin] No RBD geometries loaded from %s", rbd_geojson.name)
        return {"facilities_checked": 0, "facilities_linked": 0, "rbds_loaded": 0}

    logger.info("[SpatialJoin] Loaded %d RBD polygons", len(rbd_info))

    # 2. Build spatial index
    geoms = [info[0] for info in rbd_info]
    tree = STRtree(geoms)

    # 3. Query facilities with lat/lon from graph
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

    # 4. Point-in-polygon join
    linked = 0
    for row in facility_rows:
        fac_iri: URIRef = row[0]  # type: ignore[assignment]
        lat = float(row[1])
        lon = float(row[2])
        point = Point(lon, lat)  # shapely uses (x=lon, y=lat)

        # Find RBD polygons that contain this point
        candidate_indices = tree.query(point, predicate="within")
        for idx in candidate_indices:
            _, catchment_iri, _ = rbd_info[idx]
            graph.add((fac_iri, WC.locatedInCatchment, catchment_iri))
            linked += 1
            break  # link to first matching RBD only

    logger.info("[SpatialJoin] Linked %d / %d facilities to RBDs", linked, len(facility_rows))
    return {
        "facilities_checked": len(facility_rows),
        "facilities_linked": linked,
        "rbds_loaded": len(rbd_info),
    }
