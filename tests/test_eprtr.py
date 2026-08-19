"""Unit tests for E-PRTR ingester and mapper."""

from __future__ import annotations

import io
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from rdflib import Graph, RDF, URIRef

from water_ontology.ingesters.eprtr import (
    EprtrIngester,
    _event_id,
    _normalise_medium,
    _pollutant_id,
)
from water_ontology.mapping.eprtr_mapper import EprtrMapper
from water_ontology.models import EmissionEvent, IndustrialFacility, Pollutant

WCD = "https://w3id.org/water-contamination/data/"
WC = "https://w3id.org/water-contamination/"


# ── Utility function tests ─────────────────────────────────────────────────────

def test_normalise_medium_maps_correctly() -> None:
    assert _normalise_medium("AIR") == "air"
    assert _normalise_medium("Water") == "water"
    assert _normalise_medium("LAND") == "land"
    assert _normalise_medium("unknown") == "water"  # default


def test_pollutant_id_prefers_cas() -> None:
    assert _pollutant_id("NOx", "10102-44-0") == "CAS:10102-44-0"
    assert _pollutant_id("NOx", float("nan")) == "EPRTR:NOx"
    assert _pollutant_id("NOx", "") == "EPRTR:NOx"


def test_event_id_stable() -> None:
    row = pd.Series({"facility_id": "42", "pollutant_code": "NOx", "reporting_year": 2020})
    assert _event_id(row, "NOx") == "EPRTR:42:NOx:2020"


# ── Mapper tests ───────────────────────────────────────────────────────────────

class TestEprtrMapper:
    def test_add_facility_creates_individual(self, empty_graph: Graph) -> None:
        mapper = EprtrMapper(empty_graph)
        fac = IndustrialFacility(
            facility_id="FAC001",
            name="Test Plant",
            country_code="DE",
            lat=51.5,
            lon=9.0,
        )
        mapper.add_facility(fac)

        iri = URIRef(f"{WCD}facility/FAC001")
        assert (iri, None, None) in empty_graph

    def test_add_facility_includes_coordinates(self, empty_graph: Graph) -> None:
        mapper = EprtrMapper(empty_graph)
        fac = IndustrialFacility(
            facility_id="FAC002", name="X", country_code="FR", lat=48.8, lon=2.3
        )
        mapper.add_facility(fac)

        lat_prop = URIRef("http://www.w3.org/2003/01/geo/wgs84_pos#lat")
        iri = URIRef(f"{WCD}facility/FAC002")
        values = list(empty_graph.objects(iri, lat_prop))
        assert len(values) == 1
        assert float(values[0]) == pytest.approx(48.8)

    def test_add_pollutant(self, empty_graph: Graph) -> None:
        mapper = EprtrMapper(empty_graph)
        pol = Pollutant(pollutant_id="CAS:7440-38-2", name="Arsenic", medium="water")
        mapper.add_pollutant(pol)

        iri = URIRef(f"{WCD}pollutant/CAS_7440-38-2")
        assert (iri, None, None) in empty_graph

    def test_add_emission_event_links_facility_and_pollutant(self, empty_graph: Graph) -> None:
        mapper = EprtrMapper(empty_graph)

        fac = IndustrialFacility(facility_id="FAC003", name="Y", country_code="PL")
        pol = Pollutant(pollutant_id="CAS:7440-38-2", name="Arsenic", medium="water")
        mapper.add_facility(fac)
        mapper.add_pollutant(pol)

        event = EmissionEvent(
            event_id="EPRTR:FAC003:As:2019",
            facility_id="FAC003",
            pollutant_id="CAS:7440-38-2",
            reporting_year=2019,
            quantity_kg=500.0,
            medium="water",
        )
        mapper.add_emission_event(event)

        fac_iri = URIRef(f"{WCD}facility/FAC003")
        ev_iri = URIRef(f"{WCD}emission/EPRTR_FAC003_As_2019")
        has_event = URIRef(f"{WC}hasEmissionEvent")

        assert (fac_iri, has_event, ev_iri) in empty_graph


# ── Model validation tests ─────────────────────────────────────────────────────

def test_emission_event_rejects_bad_year() -> None:
    with pytest.raises(Exception):
        EmissionEvent(
            event_id="x",
            facility_id="1",
            pollutant_id="p",
            reporting_year=1800,
            medium="water",
        )


def test_emission_event_rejects_bad_medium() -> None:
    with pytest.raises(Exception):
        EmissionEvent(
            event_id="x",
            facility_id="1",
            pollutant_id="p",
            reporting_year=2020,
            medium="smoke",
        )


# ── EprtrIngester.ingest() integration ────────────────────────────────────────

def _make_eprtr_ingester(graph: Graph) -> EprtrIngester:
    cfg = MagicMock()
    cfg.local_zip = None
    cfg.extract_to = None
    cfg.encoding = "utf-8-sig"
    cfg.chunksize = 50000
    cfg.facilities_file = "F2_4_Water_Releases_Facilities.csv"
    cfg.releases_file = "F2_4_Water_Releases_Facilities.csv"
    return EprtrIngester(graph, cfg, raw_dir=Path("data/raw"))


_FACILITIES_DF = pd.DataFrame([{
    "FacilityInspireId": "FAC_INGEST_001",
    "facilityName": "Test Plant",
    "countryName": "DE",
    "Latitude": 51.5,
    "Longitude": 9.0,
    "EPRTR_SectorCode": "A",
}])

_RELEASES_DF = pd.DataFrame([{
    "facility_id": "FAC_INGEST_001",
    "pollutant_name": "Nitrate",
    "reporting_year": 2020,
    "quantity_kg": 1500.0,
    "medium": "WATER",
}])


class TestEprtrIngesterIngest:
    def test_ingest_creates_facility(self, empty_graph: Graph) -> None:
        ingester = _make_eprtr_ingester(empty_graph)
        with patch.object(ingester, "_load_facilities", return_value=[
            IndustrialFacility(facility_id="FAC_INGEST_001", name="Test Plant", country_code="DE", lat=51.5, lon=9.0)
        ]):
            with patch.object(ingester, "_iter_releases", return_value=iter([_RELEASES_DF])):
                counts = ingester.ingest()

        fac_iri = URIRef(f"{WCD}facility/FAC_INGEST_001")
        assert (fac_iri, RDF.type, URIRef(f"{WC}IndustrialFacility")) in empty_graph
        assert counts["facilities"] == 1

    def test_ingest_creates_emission_event(self, empty_graph: Graph) -> None:
        ingester = _make_eprtr_ingester(empty_graph)
        with patch.object(ingester, "_load_facilities", return_value=[
            IndustrialFacility(facility_id="FAC_INGEST_001", name="Test Plant", country_code="DE")
        ]):
            with patch.object(ingester, "_iter_releases", return_value=iter([_RELEASES_DF])):
                counts = ingester.ingest()

        assert counts["emission_events"] == 1
        ev_class = URIRef(f"{WC}EmissionEvent")
        assert any(True for _ in empty_graph.subjects(RDF.type, ev_class))

    def test_ingest_deduplicates_pollutants(self, empty_graph: Graph) -> None:
        two_rows = pd.concat([_RELEASES_DF, _RELEASES_DF], ignore_index=True)
        ingester = _make_eprtr_ingester(empty_graph)
        with patch.object(ingester, "_load_facilities", return_value=[
            IndustrialFacility(facility_id="FAC_INGEST_001", name="Test Plant", country_code="DE")
        ]):
            with patch.object(ingester, "_iter_releases", return_value=iter([two_rows])):
                counts = ingester.ingest()

        assert counts["pollutants"] == 1  # same pollutant deduplicated
        assert counts["emission_events"] == 2
