"""Unit tests for EEA Waterbase ingester."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from rdflib import RDF, URIRef

from water_ontology.ingesters.waterbase import WaterbaseIngester, _str, _float

WCD = "https://w3id.org/water-contamination/data/"
WC = "https://w3id.org/water-contamination/"
SOSA = "http://www.w3.org/ns/sosa/"


def _make_df(with_wb_id: bool = False) -> pd.DataFrame:
    """Minimal WISE6 disaggregated row. with_wb_id tests explicit waterBodyIdentifier."""
    row: dict = {
        "monitoringSiteIdentifier": "DE_SITE_001",
        "parameterWaterBodyCategory": "RW",
        "observedPropertyDeterminandCode": "EEA_3132",
        "observedPropertyDeterminandLabel": "Nitrate",
        "phenomenonTimeSamplingDate": "2019-05-15",
        "resultObservedValue": 4.7,
        "resultUom": "mg/L",
    }
    if with_wb_id:
        row["waterBodyIdentifier"] = "DE_RW_1"
        row["waterBodyName"] = "Rhine"
        row["countryCode"] = "DE"
    return pd.DataFrame([row])


def _make_ingester(empty_graph):  # type: ignore[no-untyped-def]
    cfg = MagicMock()
    cfg.local_zip = None
    cfg.extract_to = None
    cfg.encoding = "utf-8-sig"
    cfg.chunksize = 50000
    cfg.max_rows = None
    return WaterbaseIngester(empty_graph, cfg, raw_dir=Path("data/raw"))


def _run_ingester(ingester, df: pd.DataFrame):  # type: ignore[no-untyped-def]
    with patch.object(ingester, "_find_csv", return_value=Path("fake.csv")):
        with patch("water_ontology.ingesters.waterbase.pd.read_csv", return_value=iter([df])):
            return ingester.ingest()


class TestWaterbaseIngester:
    def test_water_body_created_from_site_id_fallback(self, empty_graph):  # type: ignore[no-untyped-def]
        """WISE6 disaggregated CSV has no waterBodyIdentifier; site ID is used as proxy."""
        ingester = _make_ingester(empty_graph)
        _run_ingester(ingester, _make_df())

        wb_iri = URIRef(f"{WCD}waterbody/DE_SITE_001")
        assert (wb_iri, RDF.type, URIRef(f"{WC}WaterBody")) in empty_graph

    def test_water_body_type_set(self, empty_graph):  # type: ignore[no-untyped-def]
        ingester = _make_ingester(empty_graph)
        _run_ingester(ingester, _make_df())

        wb_iri = URIRef(f"{WCD}waterbody/DE_SITE_001")
        wb_type_prop = URIRef(f"{WC}waterBodyType")
        types = list(empty_graph.objects(wb_iri, wb_type_prop))
        assert len(types) == 1
        assert str(types[0]) == "RW"

    def test_water_body_created_from_explicit_identifier(self, empty_graph):  # type: ignore[no-untyped-def]
        """When waterBodyIdentifier IS present, it takes precedence over site ID."""
        ingester = _make_ingester(empty_graph)
        _run_ingester(ingester, _make_df(with_wb_id=True))

        wb_iri = URIRef(f"{WCD}waterbody/DE_RW_1")
        assert (wb_iri, RDF.type, URIRef(f"{WC}WaterBody")) in empty_graph

    def test_station_triple_created(self, empty_graph):  # type: ignore[no-untyped-def]
        ingester = _make_ingester(empty_graph)
        _run_ingester(ingester, _make_df())

        stn_iri = URIRef(f"{WCD}station/DE_SITE_001")
        assert (stn_iri, RDF.type, URIRef(f"{WC}MonitoringStation")) in empty_graph

    def test_observation_triple_created(self, empty_graph):  # type: ignore[no-untyped-def]
        ingester = _make_ingester(empty_graph)
        counts = _run_ingester(ingester, _make_df())

        assert counts["observations"] == 1

    def test_station_linked_to_water_body(self, empty_graph):  # type: ignore[no-untyped-def]
        ingester = _make_ingester(empty_graph)
        _run_ingester(ingester, _make_df())

        stn_iri = URIRef(f"{WCD}station/DE_SITE_001")
        wb_iri = URIRef(f"{WCD}waterbody/DE_SITE_001")
        assert (stn_iri, URIRef(f"{WC}monitors"), wb_iri) in empty_graph

    def test_deduplicates_stations(self, empty_graph):  # type: ignore[no-untyped-def]
        df = pd.concat([_make_df(), _make_df()], ignore_index=True)
        ingester = _make_ingester(empty_graph)
        counts = _run_ingester(ingester, df)

        assert counts["stations"] == 1
        assert counts["water_bodies"] == 1


def test_str_handles_nan() -> None:
    assert _str(float("nan")) == ""
    assert _str("hello") == "hello"


def test_float_handles_bad_input() -> None:
    assert _float("n/a") is None
    assert _float(3.14) == pytest.approx(3.14)
