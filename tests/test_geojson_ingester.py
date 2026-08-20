"""Unit tests for GeoJSON ingester."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from rdflib import RDF, URIRef

from water_ontology.ingesters.geojson_ingester import GeoJsonIngester, _geom_to_wkt

WCD = "https://w3id.org/water-contamination/data/"
WC = "https://w3id.org/water-contamination/"
GS = "http://www.opengis.net/ont/geosparql#"

_SAMPLE_GEOJSON = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {
                "rbdCode": "DE_1000",
                "rbdName": "Rhine District",
                "countryCode": "DE",
            },
            "geometry": {
                "type": "Point",
                "coordinates": [7.1, 50.7],
            },
        }
    ],
}


def _make_ingester(empty_graph, mode: str = "both"):  # type: ignore[no-untyped-def]
    cfg = MagicMock()
    cfg.url = "http://example.com/features.geojson"
    cfg.local_file = None
    ingester = GeoJsonIngester(empty_graph, cfg, raw_dir=MagicMock(), mode=mode)
    return ingester


class TestGeoJsonIngester:
    def _run(self, empty_graph, mode: str = "both"):  # type: ignore[no-untyped-def]
        ingester = _make_ingester(empty_graph, mode)
        with tempfile.NamedTemporaryFile(
            suffix=".geojson", mode="w", delete=False, encoding="utf-8"
        ) as f:
            json.dump(_SAMPLE_GEOJSON, f)
            ingester.local_path = Path(f.name)
        return ingester.ingest()

    def test_water_body_created(self, empty_graph) -> None:  # type: ignore[no-untyped-def]
        self._run(empty_graph, mode="waterbody")
        iri = URIRef(f"{WCD}waterbody/DE_1000")
        assert (iri, RDF.type, URIRef(f"{WC}WaterBody")) in empty_graph

    def test_catchment_created(self, empty_graph) -> None:  # type: ignore[no-untyped-def]
        self._run(empty_graph, mode="catchment")
        iri = URIRef(f"{WCD}catchment/DE_1000")
        assert (iri, RDF.type, URIRef(f"{WC}Catchment")) in empty_graph

    def test_both_mode_creates_both(self, empty_graph) -> None:  # type: ignore[no-untyped-def]
        counts = self._run(empty_graph, mode="both")
        assert counts["water_bodies"] == 1
        assert counts["catchments"] == 1

    def test_drains_to_catchment_link(self, empty_graph) -> None:  # type: ignore[no-untyped-def]
        self._run(empty_graph, mode="both")
        wb_iri = URIRef(f"{WCD}waterbody/DE_1000")
        ca_iri = URIRef(f"{WCD}catchment/DE_1000")
        drains = URIRef(f"{WC}drainsToCatchment")
        assert (wb_iri, drains, ca_iri) in empty_graph

    def test_geometry_stored(self, empty_graph) -> None:  # type: ignore[no-untyped-def]
        self._run(empty_graph, mode="waterbody")
        iri = URIRef(f"{WCD}waterbody/DE_1000")
        has_geom = URIRef(f"{GS}hasGeometry")
        geoms = list(empty_graph.objects(iri, has_geom))
        assert len(geoms) == 1
        assert "POINT" in str(geoms[0])

    def test_skips_features_without_id(self, empty_graph) -> None:  # type: ignore[no-untyped-def]
        no_id = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {}, "geometry": None}
        ]}
        ingester = _make_ingester(empty_graph, mode="waterbody")
        with tempfile.NamedTemporaryFile(
            suffix=".geojson", mode="w", delete=False, encoding="utf-8"
        ) as f:
            json.dump(no_id, f)
            ingester.local_path = Path(f.name)
        counts = ingester.ingest()
        assert counts["water_bodies"] == 0


class TestGeomToWkt:
    def test_point(self) -> None:
        wkt = _geom_to_wkt({"type": "Point", "coordinates": [7.1, 50.7]})
        assert wkt == "POINT (7.1 50.7)"

    def test_polygon(self) -> None:
        wkt = _geom_to_wkt({
            "type": "Polygon",
            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]],
        })
        assert "POLYGON" in wkt

    def test_empty_coords(self) -> None:
        assert _geom_to_wkt({"type": "Point", "coordinates": []}) == ""
