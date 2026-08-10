"""Unit tests for EEA Waterbase ingester."""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from rdflib import URIRef

from water_ontology.ingesters.waterbase import WaterbaseIngester, _str, _float

WCD = "https://w3id.org/water-contamination/data/"
WC = "https://w3id.org/water-contamination/"
SOSA = "http://www.w3.org/ns/sosa/"


def _make_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "monitoringSiteIdentifier": "DE_SITE_001",
                "monitoringSiteName": "Rhine at Bonn",
                "lat": 50.73,
                "lon": 7.09,
                "waterBodyIdentifier": "DE_RW_1",
                "waterBodyName": "Rhine",
                "countryCode": "DE",
                "parameterWaterBodyCategory": "RW",
                "observedPropertyDeterminandCode": "EEA_3132",
                "observedPropertyDeterminandLabel": "Nitrate",
                "phenomenonTimeReferenceYear": 2019,
                "resultMeanValue": 4.7,
                "resultUom": "mg/L",
            }
        ]
    )


def _make_ingester(empty_graph):  # type: ignore[no-untyped-def]
    cfg = MagicMock()
    cfg.url = "http://example.com/waterbase.xlsx"
    cfg.local_file = None
    cfg.sheet_name = 0
    ingester = WaterbaseIngester(empty_graph, cfg, raw_dir=MagicMock())
    ingester.local_path = MagicMock()
    return ingester


class TestWaterbaseIngester:
    def test_water_body_triple_created(self, empty_graph):  # type: ignore[no-untyped-def]
        ingester = _make_ingester(empty_graph)
        with patch("pandas.read_excel", return_value=_make_df()):
            ingester.ingest()

        wb_iri = URIRef(f"{WCD}waterbody/DE_RW_1")
        wb_class = URIRef(f"{WC}WaterBody")
        from rdflib import RDF
        assert (wb_iri, RDF.type, wb_class) in empty_graph

    def test_station_triple_created(self, empty_graph):  # type: ignore[no-untyped-def]
        ingester = _make_ingester(empty_graph)
        with patch("pandas.read_excel", return_value=_make_df()):
            ingester.ingest()

        stn_iri = URIRef(f"{WCD}station/DE_SITE_001")
        stn_class = URIRef(f"{WC}MonitoringStation")
        from rdflib import RDF
        assert (stn_iri, RDF.type, stn_class) in empty_graph

    def test_observation_triple_created(self, empty_graph):  # type: ignore[no-untyped-def]
        ingester = _make_ingester(empty_graph)
        with patch("pandas.read_excel", return_value=_make_df()):
            counts = ingester.ingest()

        assert counts["observations"] == 1

    def test_station_linked_to_water_body(self, empty_graph):  # type: ignore[no-untyped-def]
        ingester = _make_ingester(empty_graph)
        with patch("pandas.read_excel", return_value=_make_df()):
            ingester.ingest()

        stn_iri = URIRef(f"{WCD}station/DE_SITE_001")
        wb_iri = URIRef(f"{WCD}waterbody/DE_RW_1")
        monitors = URIRef(f"{WC}monitors")
        assert (stn_iri, monitors, wb_iri) in empty_graph

    def test_deduplicates_stations(self, empty_graph):  # type: ignore[no-untyped-def]
        df = pd.concat([_make_df(), _make_df()], ignore_index=True)
        ingester = _make_ingester(empty_graph)
        with patch("pandas.read_excel", return_value=df):
            counts = ingester.ingest()

        assert counts["stations"] == 1  # deduplicated


def test_str_handles_nan() -> None:
    import math
    assert _str(float("nan")) == ""
    assert _str("hello") == "hello"


def test_float_handles_bad_input() -> None:
    assert _float("n/a") is None
    assert _float(3.14) == pytest.approx(3.14)
