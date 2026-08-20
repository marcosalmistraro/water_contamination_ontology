"""Unit tests for spatial joiner: facility and station → RBD linking."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from rdflib import RDF, XSD, Graph, Literal, Namespace, URIRef

from water_ontology.linkers.spatial_joiner import link_facilities_to_rbds, link_stations_to_rbds

WC = Namespace("https://w3id.org/water-contamination/")
WCD = Namespace("https://w3id.org/water-contamination/data/")
GEO = Namespace("http://www.w3.org/2003/01/geo/wgs84_pos#")

# Polygon covering roughly (lon 6–8, lat 50–52) — contains our test point (7.1, 50.7)
_RBD_GEOJSON = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"rbdCode": "DE_RBD_1"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[6, 50], [8, 50], [8, 52], [6, 52], [6, 50]]],
            },
        }
    ],
}

_CATCHMENT_IRI = URIRef("https://w3id.org/water-contamination/data/catchment/DE_RBD_1")
_WB_IRI_RBD = URIRef("https://w3id.org/water-contamination/data/waterbody/DE_RBD_1")


def _write_rbd_file() -> Path:
    f = tempfile.NamedTemporaryFile(suffix=".geojson", mode="w", delete=False, encoding="utf-8")
    json.dump(_RBD_GEOJSON, f)
    f.close()
    return Path(f.name)


def _graph_with_facility(lat: float = 50.7, lon: float = 7.1) -> Graph:
    g = Graph()
    fac = URIRef("https://w3id.org/water-contamination/data/facility/FAC001")
    g.add((fac, RDF.type, WC.IndustrialFacility))
    g.add((fac, GEO.lat, Literal(lat, datatype=XSD.decimal)))
    g.add((fac, GEO.long, Literal(lon, datatype=XSD.decimal)))
    return g


def _graph_with_station(lat: float = 50.7, lon: float = 7.1) -> Graph:
    g = Graph()
    station = URIRef("https://w3id.org/water-contamination/data/station/S001")
    wb = URIRef("https://w3id.org/water-contamination/data/waterbody/S001")
    g.add((station, RDF.type, WC.MonitoringStation))
    g.add((station, WC.monitors, wb))
    g.add((station, GEO.lat, Literal(lat, datatype=XSD.decimal)))
    g.add((station, GEO.long, Literal(lon, datatype=XSD.decimal)))
    return g


class TestLinkFacilitiesToRbds:
    def test_facility_inside_polygon_gets_linked(self) -> None:
        rbd_path = _write_rbd_file()
        g = _graph_with_facility()
        counts = link_facilities_to_rbds(g, rbd_path)

        fac = URIRef("https://w3id.org/water-contamination/data/facility/FAC001")
        assert (fac, WC.locatedInCatchment, _CATCHMENT_IRI) in g
        assert counts["facilities_linked"] == 1

    def test_facility_outside_polygon_not_linked(self) -> None:
        rbd_path = _write_rbd_file()
        g = _graph_with_facility(lat=10.0, lon=10.0)  # far from RBD polygon
        counts = link_facilities_to_rbds(g, rbd_path)

        assert counts["facilities_linked"] == 0

    def test_missing_geojson_returns_zeros(self) -> None:
        g = _graph_with_facility()
        counts = link_facilities_to_rbds(g, Path("__nonexistent_rbd__.geojson"))
        assert counts == {"facilities_checked": 0, "facilities_linked": 0, "rbds_loaded": 0}

    def test_returns_expected_count_keys(self) -> None:
        rbd_path = _write_rbd_file()
        g = _graph_with_facility()
        counts = link_facilities_to_rbds(g, rbd_path)
        assert set(counts) == {"facilities_checked", "facilities_linked", "rbds_loaded"}


class TestLinkStationsToRbds:
    def test_station_water_body_inside_polygon_gets_linked(self) -> None:
        rbd_path = _write_rbd_file()
        g = _graph_with_station()
        counts = link_stations_to_rbds(g, rbd_path)

        wb = URIRef("https://w3id.org/water-contamination/data/waterbody/S001")
        assert (wb, WC.drainsToCatchment, _CATCHMENT_IRI) in g
        assert counts["stations_linked"] == 1

    def test_station_outside_polygon_not_linked(self) -> None:
        rbd_path = _write_rbd_file()
        g = _graph_with_station(lat=10.0, lon=10.0)
        counts = link_stations_to_rbds(g, rbd_path)
        assert counts["stations_linked"] == 0

    def test_station_without_coordinates_not_linked(self) -> None:
        rbd_path = _write_rbd_file()
        g = Graph()
        station = URIRef("https://w3id.org/water-contamination/data/station/S002")
        wb = URIRef("https://w3id.org/water-contamination/data/waterbody/S002")
        g.add((station, RDF.type, WC.MonitoringStation))
        g.add((station, WC.monitors, wb))
        # no lat/lon added
        counts = link_stations_to_rbds(g, rbd_path)
        assert counts["stations_checked"] == 0

    def test_missing_geojson_returns_zeros(self) -> None:
        g = _graph_with_station()
        counts = link_stations_to_rbds(g, Path("__nonexistent_rbd__.geojson"))
        assert counts == {"stations_checked": 0, "stations_linked": 0, "rbds_loaded": 0}
