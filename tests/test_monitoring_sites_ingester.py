"""Unit tests for WISE monitoring sites ingester."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from rdflib import RDF, XSD, Graph, Literal, Namespace, URIRef

from water_ontology.ingesters.monitoring_sites_ingester import (
    MonitoringSitesIngester,
    _build_lookup,
    _patch_stations,
)

WC = Namespace("https://w3id.org/water-contamination/")
WCD = Namespace("https://w3id.org/water-contamination/data/")
GEO = Namespace("http://www.w3.org/2003/01/geo/wgs84_pos#")

_SAMPLE_FEATURES = [
    {"type": "Feature", "properties": {"thematicIdIdentifier": "DE_001", "lat": 50.7, "lon": 7.1, "countryCode": "DE"}},
    {"type": "Feature", "properties": {"thematicIdIdentifier": "FR_002", "lat": 48.8, "lon": 2.3, "countryCode": "FR"}},
]

_SAMPLE_GEOJSON = {"type": "FeatureCollection", "features": _SAMPLE_FEATURES}


def _make_ingester(graph: Graph) -> MonitoringSitesIngester:
    cfg = MagicMock()
    cfg.url = "http://example.com/sites"
    cfg.local_file = None
    cfg.page_size = 1000
    ingester = MonitoringSitesIngester(graph, cfg, raw_dir=Path("data/raw"))
    # point local_path at a temp file we control in tests
    return ingester


def _write_geojson(data: dict) -> Path:
    f = tempfile.NamedTemporaryFile(suffix=".geojson", mode="w", delete=False, encoding="utf-8")
    json.dump(data, f)
    f.close()
    return Path(f.name)


class TestBuildLookup:
    def test_parses_valid_features(self) -> None:
        result = _build_lookup(_SAMPLE_FEATURES)
        assert "DE_001" in result
        assert result["DE_001"] == {"lat": 50.7, "lon": 7.1}

    def test_skips_missing_sid(self) -> None:
        features = [{"type": "Feature", "properties": {"lat": 50.0, "lon": 7.0}}]
        assert _build_lookup(features) == {}

    def test_skips_non_numeric_coords(self) -> None:
        features = [{"type": "Feature", "properties": {
            "thematicIdIdentifier": "BAD_001", "lat": "n/a", "lon": "n/a"
        }}]
        assert _build_lookup(features) == {}

    def test_skips_null_coords(self) -> None:
        features = [{"type": "Feature", "properties": {
            "thematicIdIdentifier": "NULL_001", "lat": None, "lon": None
        }}]
        assert _build_lookup(features) == {}


class TestPatchStations:
    def test_patches_matching_station(self) -> None:
        g = Graph()
        iri = URIRef("https://w3id.org/water-contamination/data/station/DE_001")
        g.add((iri, RDF.type, WC.MonitoringStation))
        station_map = {"DE_001": iri}
        sites = {"DE_001": {"lat": 50.7, "lon": 7.1}}

        patched = _patch_stations(g, station_map, sites)
        assert patched == 1
        assert (iri, GEO.lat, None) in g

    def test_does_not_double_patch(self) -> None:
        g = Graph()
        iri = URIRef("https://w3id.org/water-contamination/data/station/DE_001")
        g.add((iri, RDF.type, WC.MonitoringStation))
        g.add((iri, GEO.lat, Literal(50.7, datatype=XSD.decimal)))
        station_map = {"DE_001": iri}
        sites = {"DE_001": {"lat": 50.7, "lon": 7.1}}

        patched = _patch_stations(g, station_map, sites)
        assert patched == 0  # already had coordinates

    def test_skips_unmatched_station(self) -> None:
        g = Graph()
        iri = URIRef("https://w3id.org/water-contamination/data/station/DE_001")
        station_map = {"DE_001": iri}
        sites = {"FR_999": {"lat": 48.8, "lon": 2.3}}

        patched = _patch_stations(g, station_map, sites)
        assert patched == 0


class TestMonitoringSitesIngesterIngest:
    def _graph_with_stations(self) -> Graph:
        g = Graph()
        for sid in ("DE_001", "FR_002"):
            iri = URIRef(f"https://w3id.org/water-contamination/data/station/{sid}")
            g.add((iri, RDF.type, WC.MonitoringStation))
            g.add((iri, WC.stationId, Literal(sid, datatype=XSD.string)))
        return g

    def test_ingest_patches_coordinates(self) -> None:
        g = self._graph_with_stations()
        ingester = _make_ingester(g)
        ingester.local_path = _write_geojson(_SAMPLE_GEOJSON)
        ingester.wfd_cache = Path("nonexistent_wfd_cache.json")

        with patch.object(ingester, "_fetch_wfd_sites", return_value={}):
            counts = ingester.ingest()

        de_iri = URIRef("https://w3id.org/water-contamination/data/station/DE_001")
        assert (de_iri, GEO.lat, None) in g
        assert counts["eionet_patched"] >= 1

    def test_ingest_returns_count_keys(self) -> None:
        g = self._graph_with_stations()
        ingester = _make_ingester(g)
        ingester.local_path = _write_geojson(_SAMPLE_GEOJSON)
        ingester.wfd_cache = Path("nonexistent_wfd_cache.json")

        with patch.object(ingester, "_fetch_wfd_sites", return_value={}):
            counts = ingester.ingest()

        assert set(counts) == {"stations_patched", "eionet_patched", "wfd_patched"}
